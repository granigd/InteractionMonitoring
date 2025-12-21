"""
API endpoints for friction detection and usability analysis.

Provides endpoint for analyzing sessions for friction patterns:
- Rage clicks
- Undo/redo bursts
- Navigation thrashing
- Rapid deletions
- Eye tracking heatmap generation
"""

import io
import uuid
import numpy as np
import traceback
import sys
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_db, validate_api_key
from sessions.model import RecordingSession, InteractionEvent, GazePoint, EyeTrackingSession
from sessions.controller import find_screenshot_for_session, generate_heatmap
from analysis.schema import (
    FrictionAnalysisConfig,
    FrictionAnalysisResponse,
    ClickstreamAnalysisResponse,
    NGramItem,
    TransitionItem,
)
from analysis.friction_detector import FrictionDetector
from analysis.clickstream_analyzer import ClickstreamAnalyzer, XESExporter


router = APIRouter(prefix="/analysis", tags=["analysis"])


# ============================================================================
# Helper Functions
# ============================================================================

async def get_session_by_id(session_id: str, db: AsyncSession) -> RecordingSession:
    """
    Find a session by internal UUID or frontend session_id.
    """
    query = select(RecordingSession)
    try:
        internal_id = uuid.UUID(session_id)
        query = query.where(RecordingSession.id == internal_id)
    except ValueError:
        query = query.where(RecordingSession.session_id == session_id)

    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )

    return session


async def get_session_events(
    session_internal_id: uuid.UUID,
    db: AsyncSession,
    start_timestamp: Optional[datetime] = None,
    end_timestamp: Optional[datetime] = None,
) -> List[dict]:
    """
    Fetch events for a session as dictionaries for analysis.
    Optionally filter to a time range [start_timestamp, end_timestamp].
    Either bound can be supplied independently.
    """
    events_query = select(InteractionEvent).where(
        InteractionEvent.session_id == session_internal_id
    )

    if start_timestamp is not None:
        events_query = events_query.where(InteractionEvent.timestamp >= start_timestamp)
    if end_timestamp is not None:
        events_query = events_query.where(InteractionEvent.timestamp <= end_timestamp)

    events_query = events_query.order_by(InteractionEvent.sequence_number)

    events_result = await db.execute(events_query)
    event_records = events_result.scalars().all()

    return [
        {
            'id': str(e.id),
            'timestamp': e.timestamp,
            'sequence_number': e.sequence_number,
            'event_type': e.event_type,
            'event_kind': e.event_kind,
            'element_id': e.element_id,
            'element_type': e.element_type,
            'position_x': e.position_x,
            'position_y': e.position_y,
            'data': e.data,
        }
        for e in event_records
    ]


# ============================================================================
# Friction Analysis Endpoint
# ============================================================================

@router.get("/friction/{session_id}", response_model=FrictionAnalysisResponse)
async def analyze_session_friction(
    session_id: str,
    # Time bounds
    start_timestamp: Optional[datetime] = Query(None, description="Only analyze events at or after this timestamp (ISO 8601)"),
    end_timestamp: Optional[datetime] = Query(None, description="Only analyze events at or before this timestamp (ISO 8601)"),
    # Rage click config
    rage_click_time_window_ms: int = Query(1500, ge=500, le=5000, description="Time window for rage click detection"),
    rage_click_min_clicks: int = Query(3, ge=2, le=10, description="Minimum clicks to qualify as rage click"),
    rage_click_max_radius_px: float = Query(50.0, ge=10, le=200, description="Maximum radius for clustered clicks"),
    # Undo/redo config
    undo_redo_time_window_ms: int = Query(10000, ge=2000, le=60000, description="Time window for undo/redo burst detection"),
    undo_redo_min_operations: int = Query(3, ge=2, le=20, description="Minimum operations for burst detection"),
    # Navigation config
    nav_time_window_ms: int = Query(5000, ge=1000, le=30000, description="Time window for navigation thrash detection"),
    nav_min_changes: int = Query(5, ge=3, le=20, description="Minimum changes for thrash detection"),
    # Deletion config
    deletion_time_window_ms: int = Query(3000, ge=1000, le=10000, description="Time window for rapid deletion detection"),
    deletion_min_count: int = Query(3, ge=2, le=10, description="Minimum deletions for detection"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Perform comprehensive friction analysis on a session.

    Detects:
    - Rage clicks (rapid frustrated clicking)
    - Undo/redo bursts (excessive corrections)
    - Navigation thrashing (erratic viewport changes)
    - Rapid deletions (mass deletes)

    Returns detailed analysis with scores, events, and recommendations.

    Optionally restrict analysis to a time window via start_timestamp / end_timestamp
    (ISO 8601, e.g. 2026-01-05T18:20:42Z). Either or both bounds can be set.

    The session_id can be either:
    - The internal UUID
    - The frontend's session ID (e.g., "activity_2026-01-05T18-20-42.100Z")
    """
    print(f"\n=== FRICTION ANALYSIS START ===", file=sys.stderr)
    print(f"Session ID: {session_id}", file=sys.stderr)

    try:
        # Get session
        session = await get_session_by_id(session_id, db)
        print(f"Found session: {session.session_id}", file=sys.stderr)

        # Get events (optionally filtered by time bounds)
        events = await get_session_events(session.id, db, start_timestamp, end_timestamp)
        print(f"Loaded {len(events)} events", file=sys.stderr)
        if start_timestamp or end_timestamp:
            print(f"  Time bounds: {start_timestamp} -> {end_timestamp}", file=sys.stderr)

        if not events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session {session_id} has no events to analyze in the given time range"
            )

        # Set up configuration from query parameters
        config = FrictionAnalysisConfig(
            rage_click_time_window_ms=rage_click_time_window_ms,
            rage_click_min_clicks=rage_click_min_clicks,
            rage_click_max_radius_px=rage_click_max_radius_px,
            undo_redo_time_window_ms=undo_redo_time_window_ms,
            undo_redo_min_operations=undo_redo_min_operations,
            nav_time_window_ms=nav_time_window_ms,
            nav_min_changes=nav_min_changes,
            deletion_time_window_ms=deletion_time_window_ms,
            deletion_min_count=deletion_min_count,
        )

        # Run friction detection
        detector = FrictionDetector(config)
        analysis_result = detector.analyze_session(events, session.duration_ms)

        print(f"Analysis complete:", file=sys.stderr)
        print(f"  - Rage click events: {analysis_result['rage_clicks'].total_events}", file=sys.stderr)
        print(f"  - Undo/redo bursts: {analysis_result['undo_redo'].total_bursts}", file=sys.stderr)
        print(f"  - Navigation thrash: {analysis_result['navigation_thrash'].total_events}", file=sys.stderr)
        print(f"  - Rapid deletions: {analysis_result['rapid_deletions'].total_events}", file=sys.stderr)
        print(f"  - Overall score: {analysis_result['friction_score'].overall_score}", file=sys.stderr)

        # Build response
        response = FrictionAnalysisResponse(
            session_id=session.session_id,
            internal_id=str(session.id),
            analysis_timestamp=datetime.now(timezone.utc),
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            config=config,
            friction_score=analysis_result['friction_score'],
            rage_clicks=analysis_result['rage_clicks'],
            undo_redo=analysis_result['undo_redo'],
            navigation_thrash=analysis_result['navigation_thrash'],
            rapid_deletions=analysis_result['rapid_deletions'],
            all_indicators=analysis_result['all_indicators'],
            session_duration_ms=session.duration_ms,
            total_events_analyzed=len(events),
            events_with_friction=analysis_result['events_with_friction'],
            friction_percentage=analysis_result['friction_percentage'],
        )

        print(f"=== FRICTION ANALYSIS SUCCESS ===", file=sys.stderr)
        return response

    except HTTPException:
        raise
    except Exception as e:
        print(f"\n=== FRICTION ANALYSIS ERROR ===", file=sys.stderr)
        print(f"Exception type: {type(e).__name__}", file=sys.stderr)
        print(f"Exception: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze session: {str(e)}"
        )


# ============================================================================
# Clickstream Analysis Endpoint
# ============================================================================

@router.get("/clickstream/{session_id}", response_model=ClickstreamAnalysisResponse)
async def analyze_clickstream(
    session_id: str,
    start_timestamp: Optional[datetime] = Query(None, description="Only analyze events at or after this timestamp (ISO 8601)"),
    end_timestamp: Optional[datetime] = Query(None, description="Only analyze events at or before this timestamp (ISO 8601)"),
    top_k: int = Query(10, ge=1, le=50, description="Number of top n-grams to return"),
    granularity: str = Query(
        'full',
        pattern='^(type|kind|full)$',
        description="Event label granularity: 'type' (event_type only), 'kind' (+ event_kind), 'full' (+ element_type)"
    ),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Analyze clickstream patterns in a session.

    Granularity levels:
    - type: element_create
    - kind: element_create:createNode
    - full: element_create:createNode:CLASS__Property

    Optionally restrict analysis to a time window via start_timestamp / end_timestamp
    (ISO 8601, e.g. 2026-01-05T18:20:42Z). Either or both bounds can be set.

    Returns:
    - Top bigrams (e.g., element_create:createNode:CLASS__Property -> property_change)
    - Top trigrams
    - Transition frequencies
    - Event type distribution
    """
    print(f"\n=== CLICKSTREAM ANALYSIS START ===", file=sys.stderr)
    print(f"Session ID: {session_id}, granularity: {granularity}", file=sys.stderr)

    try:
        session = await get_session_by_id(session_id, db)
        events = await get_session_events(session.id, db, start_timestamp, end_timestamp)

        if not events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session {session_id} has no events to analyze in the given time range"
            )

        analyzer = ClickstreamAnalyzer(granularity=granularity)
        result = analyzer.analyze_session(events, top_k=top_k)

        print(f"Analysis complete: {result['total_events']} events, {len(result['top_bigrams'])} bigrams", file=sys.stderr)

        return ClickstreamAnalysisResponse(
            session_id=session.session_id,
            internal_id=str(session.id),
            analysis_timestamp=datetime.now(timezone.utc),
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            total_events=result['total_events'],
            total_events_raw=result['total_events_raw'],
            unique_event_types=result['unique_event_types'],
            event_counts=result['event_counts'],
            top_bigrams=[NGramItem(**bg) for bg in result['top_bigrams']],
            top_trigrams=[NGramItem(**tg) for tg in result['top_trigrams']],
            top_transitions=[
                TransitionItem(from_event=t['from'], to_event=t['to'], count=t['count'])
                for t in result['top_transitions']
            ],
            transition_matrix=result['transitions'],
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Clickstream analysis error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze clickstream: {str(e)}"
        )


# ============================================================================
# XES Export Endpoint
# ============================================================================

@router.get("/xes/{session_id}")
async def export_xes(
    session_id: str,
    start_timestamp: Optional[datetime] = Query(None, description="Only export events at or after this timestamp (ISO 8601)"),
    end_timestamp: Optional[datetime] = Query(None, description="Only export events at or before this timestamp (ISO 8601)"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Export session as XES format for process mining tools.

    Returns XML file compatible with ProM, Disco, PM4Py, etc.

    Optionally restrict the export to a time window via start_timestamp / end_timestamp
    (ISO 8601, e.g. 2026-01-05T18:20:42Z). Either or both bounds can be set.

    Event names use full granularity: event_type:event_kind:element_type
    """
    print(f"\n=== XES EXPORT ===", file=sys.stderr)
    print(f"Session ID: {session_id}", file=sys.stderr)

    try:
        session = await get_session_by_id(session_id, db)
        events = await get_session_events(session.id, db, start_timestamp, end_timestamp)

        if not events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session {session_id} has no events to export in the given time range"
            )

        metadata = {
            'tool_id': session.tool_id,
            'editor_type': session.editor_type,
            'user_name': session.user_name,
        }

        exporter = XESExporter()
        xes_xml = exporter.export_session(session.session_id, events, metadata)

        print(f"Exported {len(events)} events to XES", file=sys.stderr)

        return Response(
            content=xes_xml,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{session.session_id}.xes"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"XES export error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export XES: {str(e)}"
        )


# ============================================================================
# Heatmap Endpoint
# ============================================================================

@router.get("/heatmap/{eye_tracking_session_id}")
async def get_eye_tracking_heatmap(
    eye_tracking_session_id: str,
    start_timestamp: Optional[datetime] = Query(None, description="Only include gaze points at or after this timestamp (ISO 8601)"),
    end_timestamp: Optional[datetime] = Query(None, description="Only include gaze points at or before this timestamp (ISO 8601)"),
    filter_border: bool = Query(True, description="Filter out gaze points outside or exactly on the screen border (x/y <= 0 or >= screen dimension)"),
    sigma: float = Query(18, ge=1, le=100, description="Gaussian blur sigma for smoothing"),
    colormap: str = Query("hot", description="Matplotlib colormap (hot, jet, viridis, etc.)"),
    alpha: float = Query(0.45, ge=0, le=1, description="Overlay transparency (0-1)"),
    overlay: bool = Query(True, description="Overlay on screenshot if available"),
    width: Optional[int] = Query(None, ge=100, le=4000, description="Override image width"),
    height: Optional[int] = Query(None, ge=100, le=4000, description="Override image height"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Generate a heatmap image from eye tracking gaze points.

    If a screenshot exists for the session it will be overlaid on it;
    otherwise a plain heatmap on a black background is returned.

    Parameters:
    - start_timestamp: Only include gaze points at or after this time (ISO 8601)
    - end_timestamp: Only include gaze points at or before this time (ISO 8601)
    - filter_border: Drop gaze points that lie outside or exactly on the screen edge,
      i.e. x <= 0, y <= 0, x >= screen_width, y >= screen_height (default: True).
      These typically represent failed/untracked samples that defaulted to 0 or
      were clamped to the screen boundary by the eye tracker.
    - sigma: Gaussian blur sigma for smoothing (default: 18)
    - colormap: Matplotlib colormap name (default: "hot")
    - alpha: Overlay transparency when using screenshot (default: 0.45)
    - overlay: Whether to overlay on screenshot if available (default: True)
    - width/height: Override image dimensions (uses screen dimensions from session by default)

    Returns:
    - PNG image as streaming response
    """
    print(f"\n=== HEATMAP GENERATION START ===", file=sys.stderr)
    print(f"Session ID: {eye_tracking_session_id}", file=sys.stderr)

    try:
        # Resolve eye tracking session
        session_query = select(EyeTrackingSession)
        try:
            internal_id = uuid.UUID(eye_tracking_session_id)
            session_query = session_query.where(EyeTrackingSession.id == internal_id)
        except ValueError:
            session_query = session_query.where(EyeTrackingSession.session_id == eye_tracking_session_id)

        session_result = await db.execute(session_query)
        session = session_result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Eye tracking session {eye_tracking_session_id} not found"
            )

        print(f"Found session: {session.session_id}", file=sys.stderr)
        print(f"Screen dimensions: {session.screen_width}x{session.screen_height}", file=sys.stderr)

        # Fetch gaze points (optionally filtered by time bounds)
        gaze_query = select(GazePoint).where(
            GazePoint.eye_tracking_session_id == session.id
        )

        if start_timestamp is not None:
            gaze_query = gaze_query.where(GazePoint.timestamp >= start_timestamp)
        if end_timestamp is not None:
            gaze_query = gaze_query.where(GazePoint.timestamp <= end_timestamp)

        gaze_query = gaze_query.order_by(GazePoint.sequence_number)

        gaze_result = await db.execute(gaze_query)
        gaze_points = gaze_result.scalars().all()

        if start_timestamp or end_timestamp:
            print(f"  Time bounds: {start_timestamp} -> {end_timestamp}", file=sys.stderr)

        if not gaze_points:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No gaze points found for session {eye_tracking_session_id} in the given time range"
            )

        # Filter out border / out-of-bounds gaze points
        if filter_border:
            screen_w = width or session.screen_width
            screen_h = height or session.screen_height
            before_filter = len(gaze_points)
            gaze_points = [
                gp for gp in gaze_points
                if (
                    gp.x > 0
                    and gp.y > 0
                    and (screen_w is None or gp.x < screen_w)
                    and (screen_h is None or gp.y < screen_h)
                )
            ]
            filtered_count = before_filter - len(gaze_points)
            print(f"  Border filter: removed {filtered_count} of {before_filter} gaze points", file=sys.stderr)

            if not gaze_points:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No valid gaze points remain for session {eye_tracking_session_id} after border filtering"
                )

        print(f"Using {len(gaze_points)} gaze points", file=sys.stderr)

        # Extract coordinates
        x_coords = np.array([gp.x for gp in gaze_points])
        y_coords = np.array([gp.y for gp in gaze_points])

        # Determine image dimensions
        img_width = width or session.screen_width or 1920
        img_height = height or session.screen_height or 1080
        print(f"Using dimensions: {img_width}x{img_height}", file=sys.stderr)

        # Locate screenshot for overlay
        screenshot_path = None
        if overlay:
            screenshot_path = find_screenshot_for_session(session.session_id)
            if screenshot_path:
                print(f"Found screenshot: {screenshot_path}", file=sys.stderr)
            else:
                print("No screenshot found for session", file=sys.stderr)

        # Generate heatmap image
        print(f"Generating heatmap with sigma={sigma}, colormap={colormap}, alpha={alpha}", file=sys.stderr)
        image_bytes = generate_heatmap(
            x_coords=x_coords,
            y_coords=y_coords,
            width=img_width,
            height=img_height,
            sigma=sigma,
            screenshot_path=screenshot_path,
            colormap=colormap,
            alpha=alpha
        )

        print(f"Generated heatmap image: {len(image_bytes)} bytes", file=sys.stderr)
        print(f"=== HEATMAP GENERATION SUCCESS ===", file=sys.stderr)

        return StreamingResponse(
            io.BytesIO(image_bytes),
            media_type="image/png",
            headers={
                "Content-Disposition": f"inline; filename=heatmap_{session.session_id}.png",
                "X-Session-Id": session.session_id,
                "X-Gaze-Points": str(len(gaze_points)),
                "X-Has-Screenshot": str(screenshot_path is not None).lower(),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"\n=== HEATMAP GENERATION ERROR ===", file=sys.stderr)
        print(f"Exception type: {type(e).__name__}", file=sys.stderr)
        print(f"Exception: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate heatmap: {str(e)}"
        )

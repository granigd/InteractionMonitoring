"""
API endpoints for GLSP session recording management.

Generic design to support any GLSP-based modeling tool:
- bigUML (UML diagrams)
- BPMN editors
- ER diagram editors
- Any other GLSP-based tool

Provides endpoints for:
- Uploading complete recording sessions
- Listing and retrieving sessions
- Getting session statistics
- Eye tracking session upload and retrieval
- Screenshot upload
- Event filtering and analysis
"""

import uuid
import traceback
import sys
import base64
import os
import io
from datetime import datetime, timezone
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

# Heatmap generation imports
import numpy as np
from scipy.ndimage import gaussian_filter
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
from PIL import Image

from config import get_db, validate_api_key
from sessions.model import RecordingSession, InteractionEvent, GazePoint, EyeTrackingSession
from sessions.schema import (
    SessionUploadRequest,
    SessionUploadResponse,
    SessionSummary,
    SessionDetail,
    SessionListResponse,
    SessionStatsResponse,
    EventSummary,
    EyeTrackingUploadRequest,
    EyeTrackingUploadResponse,
    EyeTrackingSessionSummary,
    EyeTrackingSessionDetail,
    ScreenshotUploadRequest,
    ScreenshotUploadResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Screenshots directory - relative to the sessions folder
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"


# ============================================================================
# Helper Functions
# ============================================================================

def parse_iso_timestamp(iso_string: str) -> datetime:
    """Parse ISO timestamp string to datetime"""
    try:
        # Handle various ISO formats
        if iso_string.endswith('Z'):
            iso_string = iso_string[:-1] + '+00:00'
        return datetime.fromisoformat(iso_string)
    except ValueError as e:
        raise ValueError(f"Invalid timestamp format: {iso_string}") from e


def extract_element_info(event: dict) -> tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
    """
    Extract element ID, type, and position from event data.
    
    Handles common GLSP action structures. Tool-specific actions
    are handled generically via fallback field names.
    
    Returns:
        tuple: (element_id, element_type, position_x, position_y)
    """
    element_id = None
    element_type = None
    position_x = None
    position_y = None
    
    event_type = event.get('type', '')
    data = event.get('data', {})
    kind = data.get('kind', '')
    
    # Handle mouse click events (new format with screen/canvas coordinates)
    if event_type == 'mouse_click':
        # Prefer screen coordinates for eye-tracking correlation
        position_x = data.get('screenX') or data.get('canvasX') or data.get('x')
        position_y = data.get('screenY') or data.get('canvasY') or data.get('y')
        element_id = data.get('elementId')
        element_type = data.get('elementType')
        return element_id, element_type, position_x, position_y
    
    # Handle common GLSP action kinds
    
    # Element selection
    if kind == 'elementSelected':
        selected_ids = data.get('selectedElementsIDs', [])
        if selected_ids:
            element_id = selected_ids[0]
        # Check for mouse position in selection events
        mouse_pos = data.get('mousePosition', {})
        if mouse_pos:
            position_x = mouse_pos.get('screenX') or mouse_pos.get('canvasX') or mouse_pos.get('x')
            position_y = mouse_pos.get('screenY') or mouse_pos.get('canvasY') or mouse_pos.get('y')
    
    # Node creation
    elif kind == 'createNode':
        element_type = data.get('elementTypeId')
        location = data.get('location', {})
        position_x = location.get('x')
        position_y = location.get('y')
        # Also check for mouse position
        mouse_pos = data.get('mousePosition', {})
        if mouse_pos and not position_x:
            position_x = mouse_pos.get('screenX') or mouse_pos.get('canvasX')
            position_y = mouse_pos.get('screenY') or mouse_pos.get('canvasY')
    
    # Edge creation
    elif kind == 'createEdge':
        element_type = data.get('elementTypeId')
        element_id = data.get('sourceElementId')
    
    # Bounds change (move/resize)
    elif kind == 'changeBounds':
        new_bounds = data.get('newBounds', [])
        if new_bounds:
            first_bound = new_bounds[0]
            element_id = first_bound.get('elementId')
            new_pos = first_bound.get('newPosition', {})
            position_x = new_pos.get('x')
            position_y = new_pos.get('y')
    
    # Element deletion
    elif kind == 'deleteElement':
        element_ids = data.get('elementIds', [])
        if element_ids:
            element_id = element_ids[0]
    
    # Label editing
    elif kind == 'applyLabelEdit':
        label_id = data.get('labelId', '')
        # Extract element ID from label ID patterns
        for suffix in ['_name_label', '_label']:
            if suffix in label_id:
                element_id = label_id.rsplit(suffix, 1)[0]
                break
    
    # Property change
    elif kind == 'updateElementProperty':
        element_id = data.get('elementId')
    
    # Viewport changes
    elif kind in ('setViewport', 'center', 'fit'):
        scroll = data.get('scroll', {})
        position_x = scroll.get('x')
        position_y = scroll.get('y')
        element_ids = data.get('elementIds', [])
        if element_ids:
            element_id = element_ids[0]
    
    # Fallback: try common field names (works for most GLSP tools)
    else:
        if 'elementId' in data:
            element_id = data['elementId']
        if 'elementTypeId' in data:
            element_type = data['elementTypeId']
        # Try various position field names
        for loc_field in ['location', 'position', 'point']:
            if loc_field in data:
                loc = data[loc_field]
                position_x = loc.get('x')
                position_y = loc.get('y')
                break
        # Check for mouse position as fallback
        if not position_x and 'mousePosition' in data:
            mouse_pos = data['mousePosition']
            position_x = mouse_pos.get('screenX') or mouse_pos.get('canvasX') or mouse_pos.get('x')
            position_y = mouse_pos.get('screenY') or mouse_pos.get('canvasY') or mouse_pos.get('y')
    
    return element_id, element_type, position_x, position_y


def find_screenshot_for_session(session_id: str) -> Optional[Path]:
    """
    Find a screenshot file associated with a session ID.
    
    Looks for files matching the pattern: screenshot_{session_id}_*.png
    Returns the most recent screenshot if multiple exist.
    """
    if not SCREENSHOTS_DIR.exists():
        return None
    
    # Sanitize session ID for filename matching
    safe_session_id = session_id.replace(':', '-').replace('/', '-').replace('\\', '-')
    
    # Find all matching screenshots
    matching_files = list(SCREENSHOTS_DIR.glob(f"screenshot_{safe_session_id}_*.png"))
    
    if not matching_files:
        # Also try without sanitization for legacy files
        matching_files = list(SCREENSHOTS_DIR.glob(f"screenshot_{session_id}_*.png"))
    
    if not matching_files:
        return None
    
    # Return the most recent file
    return max(matching_files, key=lambda f: f.stat().st_mtime)


def generate_heatmap(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    width: int,
    height: int,
    sigma: float = 18,
    screenshot_path: Optional[Path] = None,
    colormap: str = "hot",
    alpha: float = 0.45
) -> bytes:
    """
    Generate a heatmap from gaze coordinates.
    
    Args:
        x_coords: Array of x coordinates
        y_coords: Array of y coordinates
        width: Image width
        height: Image height
        sigma: Gaussian blur sigma for smoothing
        screenshot_path: Optional path to screenshot for overlay
        colormap: Matplotlib colormap name
        alpha: Transparency for overlay (0-1)
    
    Returns:
        PNG image as bytes
    """
    # Clip coordinates to image bounds
    x_clipped = np.clip(x_coords, 0, width - 1)
    y_clipped = np.clip(y_coords, 0, height - 1)
    
    # Create 2D histogram
    heatmap, _, _ = np.histogram2d(
        y_clipped,  # rows
        x_clipped,  # cols
        bins=[height, width],
        range=[[0, height], [0, width]],
    )
    
    # Apply Gaussian smoothing
    heatmap_smooth = gaussian_filter(heatmap, sigma=sigma)
    
    # Normalize
    max_val = heatmap_smooth.max()
    if max_val > 0:
        heatmap_norm = heatmap_smooth / max_val
    else:
        heatmap_norm = heatmap_smooth
    
    # Create figure
    if screenshot_path and screenshot_path.exists():
        # Overlay on screenshot
        img = Image.open(screenshot_path)
        img_width, img_height = img.size
        
        # Resize heatmap if dimensions don't match
        if img_width != width or img_height != height:
            # Recalculate heatmap for screenshot dimensions
            x_scaled = x_coords * (img_width / width) if width > 0 else x_coords
            y_scaled = y_coords * (img_height / height) if height > 0 else y_coords
            x_clipped = np.clip(x_scaled, 0, img_width - 1)
            y_clipped = np.clip(y_scaled, 0, img_height - 1)
            
            heatmap, _, _ = np.histogram2d(
                y_clipped,
                x_clipped,
                bins=[img_height, img_width],
                range=[[0, img_height], [0, img_width]],
            )
            heatmap_smooth = gaussian_filter(heatmap, sigma=sigma)
            max_val = heatmap_smooth.max()
            if max_val > 0:
                heatmap_norm = heatmap_smooth / max_val
            else:
                heatmap_norm = heatmap_smooth
        
        # Calculate figure size to match image aspect ratio
        dpi = 100
        fig_width = img_width / dpi
        fig_height = img_height / dpi
        
        fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
        ax.imshow(img)
        ax.imshow(heatmap_norm, origin="upper", alpha=alpha, cmap=colormap)
    else:
        # Plain heatmap
        dpi = 100
        fig_width = width / dpi
        fig_height = height / dpi
        
        fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
        ax.imshow(heatmap_norm, origin="upper", cmap=colormap)
    
    ax.axis("off")
    plt.tight_layout(pad=0)
    
    # Save to bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=dpi, bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    
    buf.seek(0)
    return buf.getvalue()


# ============================================================================
# Session Upload
# ============================================================================

@router.post("", response_model=SessionUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_session(
    request: SessionUploadRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Upload a complete recording session with all events.
    
    This endpoint accepts the full JSON export from any GLSP-based tool
    and stores it in the database for later analysis.
    
    Required fields:
    - sessionId: Unique session identifier
    - startTime: ISO timestamp
    - toolId: Tool identifier (e.g., "bigUML", "bpmn-glsp")
    
    Optional fields:
    - editorType: Type of diagram (e.g., "activity", "class", "bpmn")
    - modelFile, modelFilePath: Model file information
    - user, workspace: User context
    """
    session_meta = request.session
    events = request.events
    
    # Check if session already exists
    existing = await db.execute(
        select(RecordingSession).where(RecordingSession.session_id == session_meta.sessionId)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session {session_meta.sessionId} already exists"
        )
    
    try:
        # Parse timestamps
        start_time = parse_iso_timestamp(session_meta.startTime)
        end_time = parse_iso_timestamp(session_meta.endTime) if session_meta.endTime else None
        
        # Calculate duration
        duration_ms = None
        if start_time and end_time:
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        # Create session record
        session_id = uuid.uuid4()
        session_record = RecordingSession(
            id=session_id,
            session_id=session_meta.sessionId,
            tool_id=session_meta.toolId,
            tool_version=session_meta.toolVersion,
            editor_type=session_meta.editorType or "unknown",
            model_file=session_meta.modelFile,
            model_file_path=session_meta.modelFilePath,
            user_name=session_meta.user,
            workspace=session_meta.workspace,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            total_events=len(events),
            extra_data={
                "original_total_events": session_meta.totalEvents,
                "upload_time": datetime.now(timezone.utc).isoformat(),
                **(session_meta.extra or {})
            }
        )
        db.add(session_record)
        
        # Create event records
        for seq_num, event in enumerate(events):
            event_timestamp = parse_iso_timestamp(event.timestamp)
            event_kind = event.data.get('kind')
            element_id, element_type, pos_x, pos_y = extract_element_info(event.__dict__)
            
            event_record = InteractionEvent(
                id=uuid.uuid4(),
                session_id=session_id,
                timestamp=event_timestamp,
                sequence_number=seq_num,
                event_type=event.type,
                event_kind=event_kind,
                element_id=element_id,
                element_type=element_type,
                position_x=pos_x,
                position_y=pos_y,
                data=event.data
            )
            db.add(event_record)
        
        await db.commit()
        
        return SessionUploadResponse(
            success=True,
            session_id=session_meta.sessionId,
            internal_id=str(session_id),
            tool_id=session_meta.toolId,
            events_stored=len(events),
            message=f"Successfully stored {session_meta.toolId}/{session_meta.editorType or 'unknown'} session with {len(events)} events"
        )
        
    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store session: {str(e)}"
        )


# ============================================================================
# Session Retrieval
# ============================================================================

@router.get("", response_model=SessionListResponse)
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tool_id: Optional[str] = Query(None, description="Filter by tool (bigUML, bpmn-glsp, etc.)"),
    editor_type: Optional[str] = Query(None, description="Filter by editor type (activity, class, bpmn, etc.)"),
    user_name: Optional[str] = Query(None, description="Filter by user name"),
    start_date: Optional[datetime] = Query(None, description="Filter sessions starting after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter sessions starting before this date"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    List recording sessions with pagination and filtering.
    
    Supports filtering by:
    - tool_id: bigUML, bpmn-glsp, er-glsp, etc.
    - editor_type: activity, class, bpmn, er, etc.
    - user_name: Filter by user
    - start_date/end_date: Filter by session start time
    """
    # Build query
    query = select(RecordingSession)
    count_query = select(func.count(RecordingSession.id))
    
    # Apply filters
    filters = []
    if tool_id:
        filters.append(RecordingSession.tool_id == tool_id)
    if editor_type:
        filters.append(RecordingSession.editor_type == editor_type)
    if user_name:
        filters.append(RecordingSession.user_name == user_name)
    if start_date:
        filters.append(RecordingSession.start_time >= start_date)
    if end_date:
        filters.append(RecordingSession.start_time <= end_date)
    
    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Apply pagination and ordering
    query = query.order_by(RecordingSession.start_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    # Convert to response format
    session_summaries = [
        SessionSummary(
            id=str(s.id),
            session_id=s.session_id,
            tool_id=s.tool_id,
            tool_version=s.tool_version,
            editor_type=s.editor_type,
            model_file=s.model_file,
            user_name=s.user_name,
            start_time=s.start_time,
            end_time=s.end_time,
            duration_ms=s.duration_ms,
            total_events=s.total_events,
            created_at=s.created_at
        )
        for s in sessions
    ]
    
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    
    return SessionListResponse(
        sessions=session_summaries,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/stats", response_model=SessionStatsResponse)
async def get_session_stats(
    tool_id: Optional[str] = Query(None, description="Filter stats by tool"),
    editor_type: Optional[str] = Query(None, description="Filter stats by editor type"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Get aggregate statistics for all sessions.
    
    Returns:
    - Total sessions and events
    - Sessions by tool
    - Sessions by editor type
    - Sessions by user
    - Average session duration
    - Events by type breakdown
    """
    # Build base filter
    filters = []
    if tool_id:
        filters.append(RecordingSession.tool_id == tool_id)
    if editor_type:
        filters.append(RecordingSession.editor_type == editor_type)
    
    # Total sessions
    sessions_query = select(func.count(RecordingSession.id))
    if filters:
        sessions_query = sessions_query.where(and_(*filters))
    total_sessions_result = await db.execute(sessions_query)
    total_sessions = total_sessions_result.scalar() or 0
    
    # Total events
    events_query = select(func.sum(RecordingSession.total_events))
    if filters:
        events_query = events_query.where(and_(*filters))
    total_events_result = await db.execute(events_query)
    total_events = total_events_result.scalar() or 0
    
    # Sessions by tool
    tool_query = select(
        RecordingSession.tool_id, 
        func.count(RecordingSession.id)
    ).group_by(RecordingSession.tool_id)
    tool_result = await db.execute(tool_query)
    sessions_by_tool = {row[0]: row[1] for row in tool_result.fetchall()}
    
    # Sessions by editor type
    editor_type_query = select(
        RecordingSession.editor_type, 
        func.count(RecordingSession.id)
    ).group_by(RecordingSession.editor_type)
    editor_type_result = await db.execute(editor_type_query)
    sessions_by_editor_type = {row[0]: row[1] for row in editor_type_result.fetchall()}
    
    # Sessions by user
    user_query = select(
        RecordingSession.user_name, 
        func.count(RecordingSession.id)
    ).where(
        RecordingSession.user_name.isnot(None)
    ).group_by(RecordingSession.user_name)
    user_result = await db.execute(user_query)
    sessions_by_user = {row[0]: row[1] for row in user_result.fetchall()}
    
    # Average duration
    avg_duration_query = select(func.avg(RecordingSession.duration_ms)).where(
        RecordingSession.duration_ms.isnot(None)
    )
    if filters:
        avg_duration_query = avg_duration_query.where(and_(*filters))
    avg_duration_result = await db.execute(avg_duration_query)
    avg_duration = avg_duration_result.scalar()
    
    # Average events per session
    avg_events = total_events / total_sessions if total_sessions > 0 else 0
    
    # Events by type
    events_by_type_query = select(
        InteractionEvent.event_type,
        func.count(InteractionEvent.id)
    ).group_by(InteractionEvent.event_type)
    events_by_type_result = await db.execute(events_by_type_query)
    events_by_type = {row[0]: row[1] for row in events_by_type_result.fetchall()}
    
    return SessionStatsResponse(
        total_sessions=total_sessions,
        total_events=total_events,
        sessions_by_tool=sessions_by_tool,
        sessions_by_editor_type=sessions_by_editor_type,
        sessions_by_user=sessions_by_user,
        avg_session_duration_ms=avg_duration,
        avg_events_per_session=avg_events,
        events_by_type=events_by_type
    )


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    include_events: bool = Query(True, description="Include event list in response"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Get detailed information about a specific session.
    
    The session_id can be either:
    - The internal UUID
    - The frontend's session ID (e.g., "activity_2026-01-05T18-20-42.100Z")
    """
    # Try to find by internal ID first, then by session_id
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
    
    # Get events if requested
    events = []
    if include_events:
        events_query = select(InteractionEvent).where(
            InteractionEvent.session_id == session.id
        ).order_by(InteractionEvent.sequence_number)
        
        events_result = await db.execute(events_query)
        event_records = events_result.scalars().all()
        
        events = [
            EventSummary(
                id=str(e.id),
                timestamp=e.timestamp,
                sequence_number=e.sequence_number,
                event_type=e.event_type,
                event_kind=e.event_kind,
                element_id=e.element_id,
                element_type=e.element_type,
                position_x=e.position_x,
                position_y=e.position_y,
                data=e.data
            )
            for e in event_records
        ]
    
    return SessionDetail(
        id=str(session.id),
        session_id=session.session_id,
        tool_id=session.tool_id,
        tool_version=session.tool_version,
        editor_type=session.editor_type,
        model_file=session.model_file,
        model_file_path=session.model_file_path,
        user_name=session.user_name,
        workspace=session.workspace,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_ms=session.duration_ms,
        total_events=session.total_events,
        created_at=session.created_at,
        updated_at=session.updated_at,
        extra_data=session.extra_data,
        events=events
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Delete a session and all its associated events.
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
    
    await db.delete(session)
    await db.commit()


# ============================================================================
# Event Retrieval
# ============================================================================

@router.get("/{session_id}/events", response_model=List[EventSummary])
async def get_session_events(
    session_id: str,
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    event_kind: Optional[str] = Query(None, description="Filter by event kind"),
    element_id: Optional[str] = Query(None, description="Filter by element ID"),
    element_type: Optional[str] = Query(None, description="Filter by element type"),
    start_sequence: Optional[int] = Query(None, description="Start sequence number"),
    end_sequence: Optional[int] = Query(None, description="End sequence number"),
    limit: Optional[int] = Query(None, le=10000, description="Maximum events to return"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Get events for a specific session with optional filtering.
    """
    # Find session
    session_query = select(RecordingSession)
    try:
        internal_id = uuid.UUID(session_id)
        session_query = session_query.where(RecordingSession.id == internal_id)
    except ValueError:
        session_query = session_query.where(RecordingSession.session_id == session_id)
    
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Build events query
    query = select(InteractionEvent).where(InteractionEvent.session_id == session.id)
    
    if event_type:
        query = query.where(InteractionEvent.event_type == event_type)
    if event_kind:
        query = query.where(InteractionEvent.event_kind == event_kind)
    if element_id:
        query = query.where(InteractionEvent.element_id == element_id)
    if element_type:
        query = query.where(InteractionEvent.element_type == element_type)
    if start_sequence is not None:
        query = query.where(InteractionEvent.sequence_number >= start_sequence)
    if end_sequence is not None:
        query = query.where(InteractionEvent.sequence_number <= end_sequence)
    
    query = query.order_by(InteractionEvent.sequence_number)
    
    if limit:
        query = query.limit(limit)
    
    result = await db.execute(query)
    events = result.scalars().all()
    
    return [
        EventSummary(
            id=str(e.id),
            timestamp=e.timestamp,
            sequence_number=e.sequence_number,
            event_type=e.event_type,
            event_kind=e.event_kind,
            element_id=e.element_id,
            element_type=e.element_type,
            position_x=e.position_x,
            position_y=e.position_y,
            data=e.data
        )
        for e in events
    ]


# ============================================================================
# Eye Tracking Sessions
# ============================================================================

@router.post("/eye-tracking", response_model=EyeTrackingUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_eye_tracking_session(
    request: EyeTrackingUploadRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Upload a complete eye tracking session with all gaze points.
    """
    print(f"\n=== EYE TRACKING UPLOAD START ===", file=sys.stderr)
    
    try:
        metadata = request.metadata
        gaze_points = request.gazePoints
        linked_session_id = request.linkedSessionId
        
        print(f"Metadata: {metadata}", file=sys.stderr)
        print(f"Gaze points count: {len(gaze_points)}", file=sys.stderr)
        print(f"Linked session ID: {linked_session_id}", file=sys.stderr)
        
        # Look up linked recording session if provided
        linked_recording_session = None
        linked_recording_session_internal_id = None
        
        if linked_session_id:
            session_query = select(RecordingSession)
            try:
                internal_id = uuid.UUID(linked_session_id)
                session_query = session_query.where(RecordingSession.id == internal_id)
            except ValueError:
                session_query = session_query.where(RecordingSession.session_id == linked_session_id)
            
            result = await db.execute(session_query)
            linked_recording_session = result.scalar_one_or_none()
            
            if linked_recording_session:
                linked_recording_session_internal_id = linked_recording_session.id
            else:
                print(f"Warning: Linked session {linked_session_id} not found. Eye tracking will be standalone.", file=sys.stderr)
        
        # Parse timestamps
        export_time = parse_iso_timestamp(metadata.exportTime)
        print(f"Export time: {export_time}", file=sys.stderr)
        
        # Calculate start/end time from gaze points
        if gaze_points:
            start_timestamp_ms = gaze_points[0].timestamp
            end_timestamp_ms = gaze_points[-1].timestamp
            start_time = datetime.fromtimestamp(start_timestamp_ms / 1000, tz=timezone.utc)
            end_time = datetime.fromtimestamp(end_timestamp_ms / 1000, tz=timezone.utc)
            print(f"Start time: {start_time}, End time: {end_time}", file=sys.stderr)
        else:
            start_time = export_time
            end_time = export_time
        
        # Generate session ID
        eye_tracking_session_id = linked_session_id or f"eye_tracking_{export_time.strftime('%Y-%m-%dT%H-%M-%S')}"
        print(f"Eye tracking session ID: {eye_tracking_session_id}", file=sys.stderr)
        
        # Create eye tracking session record
        et_session_id = uuid.uuid4()
        print(f"Creating EyeTrackingSession with id={et_session_id}", file=sys.stderr)
        
        et_session = EyeTrackingSession(
            id=et_session_id,
            recording_session_id=linked_recording_session_internal_id,
            session_id=eye_tracking_session_id,
            start_time=start_time,
            end_time=end_time,
            duration_ms=metadata.duration,
            total_gaze_points=metadata.totalPoints,
            tracker_type=metadata.trackerType or "webgazer",
            screen_width=metadata.screenWidth,
            screen_height=metadata.screenHeight,
            calibration_points=metadata.calibrationPoints,
            extra_data={
                "export_time": metadata.exportTime,
                "upload_time": datetime.now(timezone.utc).isoformat(),
            }
        )
        db.add(et_session)
        print(f"Added EyeTrackingSession to db", file=sys.stderr)
        
        # Create gaze point records
        print(f"Creating {len(gaze_points)} gaze point records...", file=sys.stderr)
        for seq_num, gp in enumerate(gaze_points):
            gaze_timestamp = datetime.fromtimestamp(gp.timestamp / 1000, tz=timezone.utc)
            
            gaze_record = GazePoint(
                id=uuid.uuid4(),
                eye_tracking_session_id=et_session_id,
                session_id=linked_recording_session_internal_id,
                timestamp=gaze_timestamp,
                sequence_number=seq_num,
                x=gp.x,
                y=gp.y,
            )
            db.add(gaze_record)
        
        print(f"Committing to database...", file=sys.stderr)
        await db.commit()
        print(f"=== EYE TRACKING UPLOAD SUCCESS ===", file=sys.stderr)
        
        return EyeTrackingUploadResponse(
            success=True,
            eye_tracking_session_id=str(et_session_id),
            gaze_points_stored=len(gaze_points),
            linked_recording_session_id=str(linked_recording_session_internal_id) if linked_recording_session_internal_id else None,
            message=f"Successfully stored eye tracking session with {len(gaze_points)} gaze points" +
                    (f" (linked to recording session {linked_session_id})" if linked_recording_session else "")
        )
        
    except ValueError as e:
        print(f"\n=== EYE TRACKING UPLOAD ValueError ===", file=sys.stderr)
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"\n=== EYE TRACKING UPLOAD ERROR ===", file=sys.stderr)
        print(f"Exception type: {type(e).__name__}", file=sys.stderr)
        print(f"Exception: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store eye tracking session: {str(e)}"
        )


@router.get("/eye-tracking", response_model=List[EyeTrackingSessionSummary])
async def list_eye_tracking_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    linked_only: bool = Query(False, description="Only show sessions linked to recording sessions"),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    List all eye tracking sessions with pagination.
    """
    query = select(EyeTrackingSession)
    
    if linked_only:
        query = query.where(EyeTrackingSession.recording_session_id.isnot(None))
    
    query = query.order_by(EyeTrackingSession.start_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    return [
        EyeTrackingSessionSummary(
            id=str(s.id),
            session_id=s.session_id,
            recording_session_id=str(s.recording_session_id) if s.recording_session_id else None,
            start_time=s.start_time,
            end_time=s.end_time,
            duration_ms=s.duration_ms,
            total_gaze_points=s.total_gaze_points or 0,
            total_fixations=s.total_fixations or 0,
            avg_confidence=s.avg_confidence,
            tracker_type=s.tracker_type,
            created_at=s.created_at
        )
        for s in sessions
    ]


@router.get("/eye-tracking/{eye_tracking_session_id}", response_model=EyeTrackingSessionDetail)
async def get_eye_tracking_session(
    eye_tracking_session_id: str,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Get detailed information about a specific eye tracking session.
    """
    query = select(EyeTrackingSession)
    try:
        internal_id = uuid.UUID(eye_tracking_session_id)
        query = query.where(EyeTrackingSession.id == internal_id)
    except ValueError:
        query = query.where(EyeTrackingSession.session_id == eye_tracking_session_id)
    
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Eye tracking session {eye_tracking_session_id} not found"
        )
    
    return EyeTrackingSessionDetail(
        id=str(session.id),
        session_id=session.session_id,
        recording_session_id=str(session.recording_session_id) if session.recording_session_id else None,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_ms=session.duration_ms,
        total_gaze_points=session.total_gaze_points or 0,
        total_fixations=session.total_fixations or 0,
        avg_confidence=session.avg_confidence,
        tracker_type=session.tracker_type,
        screen_width=session.screen_width,
        screen_height=session.screen_height,
        calibration_points=session.calibration_points,
        created_at=session.created_at,
        updated_at=session.updated_at,
        extra_data=session.extra_data
    )


@router.get("/eye-tracking/{eye_tracking_session_id}/gaze-points")
async def get_eye_tracking_gaze_points(
    eye_tracking_session_id: str,
    start_sequence: Optional[int] = Query(None),
    end_sequence: Optional[int] = Query(None),
    limit: int = Query(10000, le=100000),
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Get gaze points for an eye tracking session.
    """
    # Find session
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
    
    # Build query
    query = select(GazePoint).where(GazePoint.eye_tracking_session_id == session.id)
    
    if start_sequence is not None:
        query = query.where(GazePoint.sequence_number >= start_sequence)
    if end_sequence is not None:
        query = query.where(GazePoint.sequence_number <= end_sequence)
    
    query = query.order_by(GazePoint.sequence_number).limit(limit)
    
    result = await db.execute(query)
    gaze_points = result.scalars().all()
    
    return {
        "eye_tracking_session_id": eye_tracking_session_id,
        "count": len(gaze_points),
        "gaze_points": [
            {
                "id": str(gp.id),
                "timestamp": gp.timestamp.isoformat(),
                "sequence_number": gp.sequence_number,
                "x": gp.x,
                "y": gp.y,
            }
            for gp in gaze_points
        ]
    }


@router.get("/eye-tracking/{eye_tracking_session_id}/heatmap", deprecated=True, include_in_schema=False)
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
    Deprecated: use GET /analysis/heatmap/{eye_tracking_session_id} instead.
    """
    print(f"\n=== HEATMAP GENERATION START ===", file=sys.stderr)
    print(f"Session ID: {eye_tracking_session_id}", file=sys.stderr)
    
    try:
        # Find eye tracking session
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

        print(f"Found {len(gaze_points)} gaze points", file=sys.stderr)
        
        # Extract coordinates
        x_coords = np.array([gp.x for gp in gaze_points])
        y_coords = np.array([gp.y for gp in gaze_points])
        
        # Determine image dimensions
        img_width = width or session.screen_width or 1920
        img_height = height or session.screen_height or 1080
        print(f"Using dimensions: {img_width}x{img_height}", file=sys.stderr)
        
        # Check for screenshot
        screenshot_path = None
        if overlay:
            screenshot_path = find_screenshot_for_session(session.session_id)
            if screenshot_path:
                print(f"Found screenshot: {screenshot_path}", file=sys.stderr)
            else:
                print("No screenshot found for session", file=sys.stderr)
        
        # Generate heatmap
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
        
        # Return as streaming response
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


@router.delete("/eye-tracking/{eye_tracking_session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_eye_tracking_session(
    eye_tracking_session_id: str,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(validate_api_key)
):
    """
    Delete an eye tracking session and all its gaze points.
    """
    query = select(EyeTrackingSession)
    try:
        internal_id = uuid.UUID(eye_tracking_session_id)
        query = query.where(EyeTrackingSession.id == internal_id)
    except ValueError:
        query = query.where(EyeTrackingSession.session_id == eye_tracking_session_id)
    
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Eye tracking session {eye_tracking_session_id} not found"
        )
    
    await db.delete(session)
    await db.commit()


# ============================================================================
# Screenshot Upload
# ============================================================================

@router.post("/screenshot", response_model=ScreenshotUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_screenshot(
    request: ScreenshotUploadRequest,
    auth: bool = Depends(validate_api_key)
):
    """
    Upload a screenshot image (PNG format) and store it on disk.
    
    The image should be base64 encoded (without the data:image/png;base64, prefix).
    Optionally link it to a session ID for organization.
    
    Screenshots are stored in the sessions/screenshots directory.
    """
    print(f"\n=== SCREENSHOT UPLOAD START ===", file=sys.stderr)
    
    try:
        # Ensure screenshots directory exists
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Screenshots directory: {SCREENSHOTS_DIR}", file=sys.stderr)
        
        # Parse timestamp
        if request.timestamp:
            timestamp = parse_iso_timestamp(request.timestamp)
        else:
            timestamp = datetime.now(timezone.utc)
        
        # Generate filename
        timestamp_str = timestamp.strftime('%Y-%m-%dT%H-%M-%S-%f')[:-3]  # Remove last 3 digits of microseconds
        
        if request.linkedSessionId:
            # Sanitize session ID for filename (replace colons and other invalid chars)
            safe_session_id = request.linkedSessionId.replace(':', '-').replace('/', '-').replace('\\', '-')
            filename = f"screenshot_{safe_session_id}_{timestamp_str}.png"
        else:
            filename = f"screenshot_{timestamp_str}.png"
        
        filepath = SCREENSHOTS_DIR / filename
        print(f"Saving screenshot to: {filepath}", file=sys.stderr)
        
        # Decode base64 image data
        try:
            # Remove data URL prefix if present
            image_data = request.imageData
            if image_data.startswith('data:'):
                # Remove the data:image/png;base64, prefix
                image_data = image_data.split(',', 1)[1]
            
            image_bytes = base64.b64decode(image_data)
            print(f"Decoded image size: {len(image_bytes)} bytes", file=sys.stderr)
        except Exception as e:
            print(f"Base64 decode error: {e}", file=sys.stderr)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64 image data: {str(e)}"
            )
        
        # Write image to file
        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        
        print(f"=== SCREENSHOT UPLOAD SUCCESS ===", file=sys.stderr)
        
        return ScreenshotUploadResponse(
            success=True,
            filename=filename,
            filepath=str(filepath),
            linked_session_id=request.linkedSessionId,
            message=f"Screenshot saved successfully as {filename}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n=== SCREENSHOT UPLOAD ERROR ===", file=sys.stderr)
        print(f"Exception type: {type(e).__name__}", file=sys.stderr)
        print(f"Exception: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save screenshot: {str(e)}"
        )


@router.get("/screenshots")
async def list_screenshots(
    linked_session_id: Optional[str] = Query(None, description="Filter by linked session ID"),
    auth: bool = Depends(validate_api_key)
):
    """
    List all screenshots stored on disk.
    Optionally filter by linked session ID.
    """
    try:
        if not SCREENSHOTS_DIR.exists():
            return {"screenshots": [], "count": 0}
        
        screenshots = []
        for filepath in SCREENSHOTS_DIR.glob("*.png"):
            stat = filepath.stat()
            screenshot_info = {
                "filename": filepath.name,
                "filepath": str(filepath),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
            
            # Try to extract session ID from filename
            if filepath.name.startswith("screenshot_") and "_" in filepath.name[11:]:
                parts = filepath.name[11:].rsplit("_", 1)
                if len(parts) == 2:
                    screenshot_info["linked_session_id"] = parts[0]
            
            # Filter by linked session ID if provided
            if linked_session_id:
                if screenshot_info.get("linked_session_id") == linked_session_id:
                    screenshots.append(screenshot_info)
            else:
                screenshots.append(screenshot_info)
        
        # Sort by created time, newest first
        screenshots.sort(key=lambda x: x["created_at"], reverse=True)
        
        return {"screenshots": screenshots, "count": len(screenshots)}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list screenshots: {str(e)}"
        )

"""
Pydantic schemas for friction detection analysis API.

Provides request/response models for:
- Rage click detection
- Undo/redo pattern analysis
- Navigation thrash detection
- Rapid deletion detection
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class FrictionType(str, Enum):
    """Types of friction indicators"""
    RAGE_CLICK = "rage_click"
    UNDO_REDO_BURST = "undo_redo_burst"
    NAVIGATION_THRASH = "navigation_thrash"
    RAPID_ELEMENT_DELETION = "rapid_element_deletion"


class FrictionSeverity(str, Enum):
    """Severity levels for friction indicators"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# Friction Event Schemas
# ============================================================================

class RageClickEvent(BaseModel):
    """A detected rage click event"""
    start_time: datetime
    end_time: datetime
    click_count: int
    duration_ms: int
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    radius_px: float = Field(description="Radius in pixels containing all clicks")
    element_id: Optional[str] = None
    element_type: Optional[str] = None
    severity: FrictionSeverity
    click_sequence_numbers: List[int] = Field(default_factory=list)


class UndoRedoBurst(BaseModel):
    """A detected undo/redo burst event"""
    start_time: datetime
    end_time: datetime
    undo_count: int
    redo_count: int
    total_operations: int
    duration_ms: int
    net_effect: int = Field(description="Net undo count (positive) or redo count (negative)")
    severity: FrictionSeverity
    sequence_numbers: List[int] = Field(default_factory=list)
    pattern: str = Field(description="Pattern of operations, e.g., 'UUURRU' for undo/redo")


class NavigationThrashEvent(BaseModel):
    """A detected navigation thrashing event"""
    start_time: datetime
    end_time: datetime
    viewport_changes: int
    zoom_changes: int
    scroll_events: int
    total_changes: int
    duration_ms: int
    distance_traveled_px: Optional[float] = None
    severity: FrictionSeverity
    sequence_numbers: List[int] = Field(default_factory=list)


class RapidDeletionEvent(BaseModel):
    """A detected rapid element deletion event"""
    start_time: datetime
    end_time: datetime
    deletion_count: int
    duration_ms: int
    deleted_element_types: List[str] = Field(default_factory=list)
    severity: FrictionSeverity
    sequence_numbers: List[int] = Field(default_factory=list)


# ============================================================================
# Friction Summary Schemas
# ============================================================================

class FrictionIndicator(BaseModel):
    """A single friction indicator with metadata"""
    type: FrictionType
    severity: FrictionSeverity
    timestamp: datetime
    duration_ms: int
    description: str
    details: Dict[str, Any] = Field(default_factory=dict)
    sequence_start: int
    sequence_end: int


class RageClickSummary(BaseModel):
    """Summary of rage click analysis"""
    total_events: int
    events: List[RageClickEvent]
    affected_elements: int
    total_rage_clicks: int
    avg_clicks_per_event: float
    max_clicks_in_event: int
    hotspot_positions: List[Dict[str, float]] = Field(
        default_factory=list,
        description="Common positions where rage clicks occurred"
    )


class UndoRedoSummary(BaseModel):
    """Summary of undo/redo pattern analysis"""
    total_bursts: int
    bursts: List[UndoRedoBurst]
    total_undos: int
    total_redos: int
    avg_burst_size: float
    max_burst_size: int
    time_spent_undoing_ms: int
    common_patterns: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Most common undo/redo patterns detected"
    )


class NavigationThrashSummary(BaseModel):
    """Summary of navigation thrashing analysis"""
    total_events: int
    events: List[NavigationThrashEvent]
    total_viewport_changes: int
    total_zoom_changes: int
    avg_changes_per_event: float
    total_distance_traveled_px: Optional[float] = None


class RapidDeletionSummary(BaseModel):
    """Summary of rapid deletion analysis"""
    total_events: int
    events: List[RapidDeletionEvent]
    total_deletions: int
    most_deleted_types: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# Friction Score Schema
# ============================================================================

class FrictionScore(BaseModel):
    """Overall friction score for a session"""
    overall_score: float = Field(ge=0, le=100, description="0 = no friction, 100 = maximum friction")
    rage_click_score: float = Field(ge=0, le=100)
    undo_redo_score: float = Field(ge=0, le=100)
    navigation_score: float = Field(ge=0, le=100)
    deletion_score: float = Field(ge=0, le=100)
    interpretation: str = Field(description="Human-readable interpretation of the score")
    recommendations: List[str] = Field(
        default_factory=list,
        description="Actionable recommendations based on detected friction"
    )


# ============================================================================
# Configuration Schema
# ============================================================================

class FrictionAnalysisConfig(BaseModel):
    """Configuration parameters for friction detection"""
    # Rage click detection
    rage_click_time_window_ms: int = Field(
        default=1500,
        ge=500,
        le=5000,
        description="Time window in ms to detect rapid clicks"
    )
    rage_click_min_clicks: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Minimum clicks within window to qualify as rage click"
    )
    rage_click_max_radius_px: float = Field(
        default=50.0,
        ge=10,
        le=200,
        description="Maximum pixel radius for clicks to be considered same location"
    )
    
    # Undo/redo detection
    undo_redo_time_window_ms: int = Field(
        default=10000,
        ge=2000,
        le=60000,
        description="Time window in ms to detect undo/redo bursts"
    )
    undo_redo_min_operations: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Minimum operations to qualify as burst"
    )
    
    # Navigation thrash detection
    nav_time_window_ms: int = Field(
        default=5000,
        ge=1000,
        le=30000,
        description="Time window in ms to detect navigation thrashing"
    )
    nav_min_changes: int = Field(
        default=5,
        ge=3,
        le=20,
        description="Minimum changes to qualify as thrashing"
    )
    
    # Rapid deletion detection
    deletion_time_window_ms: int = Field(
        default=3000,
        ge=1000,
        le=10000,
        description="Time window in ms to detect rapid deletions"
    )
    deletion_min_count: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Minimum deletions to qualify as rapid deletion"
    )


# ============================================================================
# Response Schema
# ============================================================================

class FrictionAnalysisResponse(BaseModel):
    """Complete friction analysis response"""
    session_id: str
    internal_id: str
    analysis_timestamp: datetime

    # Optional time bounds used for this analysis (None = full session)
    start_timestamp: Optional[datetime] = Field(None, description="Analysis start bound (inclusive), or None for full session")
    end_timestamp: Optional[datetime] = Field(None, description="Analysis end bound (inclusive), or None for full session")

    # Configuration used
    config: FrictionAnalysisConfig
    
    # Overall score
    friction_score: FrictionScore
    
    # Detailed summaries
    rage_clicks: RageClickSummary
    undo_redo: UndoRedoSummary
    navigation_thrash: NavigationThrashSummary
    rapid_deletions: RapidDeletionSummary
    
    # All friction indicators in chronological order
    all_indicators: List[FrictionIndicator] = Field(default_factory=list)
    
    # Session context
    session_duration_ms: Optional[int] = None
    total_events_analyzed: int
    events_with_friction: int
    friction_percentage: float = Field(description="Percentage of events that are friction-related")


# ============================================================================
# Clickstream Analysis Schemas
# ============================================================================

class NGramItem(BaseModel):
    """A single n-gram with count"""
    sequence: List[str]
    count: int
    label: str = Field(description="Human-readable representation, e.g., 'A → B → C'")


class TransitionItem(BaseModel):
    """A single transition (bigram)"""
    from_event: str = Field(alias="from")
    to_event: str = Field(alias="to")
    count: int
    
    class Config:
        populate_by_name = True


class ClickstreamAnalysisResponse(BaseModel):
    """Clickstream analysis response with n-grams and transitions"""
    session_id: str
    internal_id: str
    analysis_timestamp: datetime

    # Optional time bounds used for this analysis (None = full session)
    start_timestamp: Optional[datetime] = Field(None, description="Analysis start bound (inclusive), or None for full session")
    end_timestamp: Optional[datetime] = Field(None, description="Analysis end bound (inclusive), or None for full session")

    # Event statistics
    total_events: int = Field(description="Events included in analysis (after filtering)")
    total_events_raw: int = Field(description="Total events before filtering")
    unique_event_types: int
    event_counts: Dict[str, int] = Field(description="Count per event type")
    
    # N-grams
    top_bigrams: List[NGramItem] = Field(default_factory=list)
    top_trigrams: List[NGramItem] = Field(default_factory=list)
    
    # Transitions
    top_transitions: List[TransitionItem] = Field(default_factory=list)
    transition_matrix: Dict[str, Dict[str, int]] = Field(
        default_factory=dict,
        description="Full transition matrix: from_event -> to_event -> count"
    )

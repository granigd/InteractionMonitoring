"""
Pydantic schemas for GLSP session recording API.

Generic design to support any GLSP-based modeling tool:
- bigUML (UML diagrams)
- BPMN editors  
- ER diagram editors
- Any other GLSP-based tool

The schemas are flexible and accept tool-specific data in JSON fields.
"""

from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any, Dict
from datetime import datetime


# ============================================================================
# Request Schemas (for uploading sessions)
# ============================================================================

class SessionMetadata(BaseModel):
    """
    Session metadata from the frontend.
    
    Generic fields that work with any GLSP tool.
    """
    sessionId: str
    startTime: str  # ISO timestamp
    endTime: Optional[str] = None
    
    # Tool identification
    toolId: str  # e.g., "bigUML", "bpmn-glsp", "er-glsp"
    toolVersion: Optional[str] = None
    
    # Editor/Model information
    editorType: Optional[str] = None  # e.g., "activity", "class", "bpmn", "er"
    modelFile: Optional[str] = None  # Filename
    modelFilePath: Optional[str] = None  # Full path
    
    # User information
    user: Optional[str] = None
    workspace: Optional[str] = None
    totalEvents: Optional[int] = None
    
    # Tool-specific extra data
    extra: Optional[Dict[str, Any]] = None


class InteractionEventData(BaseModel):
    """
    Individual interaction event from the frontend.
    
    Generic structure that works with any GLSP tool.
    Tool-specific action data is stored in the 'data' field.
    """
    timestamp: str  # ISO timestamp
    type: str  # Event type (element_create, element_select, etc.)
    sessionId: str
    data: Dict[str, Any] = Field(default_factory=dict)  # Tool-specific action data


class SessionUploadRequest(BaseModel):
    """
    Complete session upload request.
    
    This matches the JSON structure exported by GLSP frontends:
    {
        "session": { ... },
        "events": [ ... ]
    }
    """
    session: SessionMetadata
    events: List[InteractionEventData]
    
    @model_validator(mode='after')
    def validate_events(cls, model):
        if not model.events:
            raise ValueError("events list cannot be empty")
        return model


# ============================================================================
# Response Schemas
# ============================================================================

class SessionSummary(BaseModel):
    """Summary of a recording session (for list views)"""
    id: str
    session_id: str
    tool_id: str
    tool_version: Optional[str] = None
    editor_type: Optional[str] = None
    model_file: Optional[str] = None
    user_name: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_events: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class EventSummary(BaseModel):
    """Summary of an interaction event"""
    id: str
    timestamp: datetime
    sequence_number: int
    event_type: str
    event_kind: Optional[str] = None
    element_id: Optional[str] = None
    element_type: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    data: Dict[str, Any]
    
    class Config:
        from_attributes = True


class SessionDetail(BaseModel):
    """Detailed session information including events"""
    id: str
    session_id: str
    tool_id: str
    tool_version: Optional[str] = None
    editor_type: Optional[str] = None
    model_file: Optional[str] = None
    model_file_path: Optional[str] = None
    user_name: Optional[str] = None
    workspace: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_events: int
    created_at: datetime
    updated_at: datetime
    extra_data: Optional[Dict[str, Any]] = None
    events: List[EventSummary] = []
    
    class Config:
        from_attributes = True


class SessionUploadResponse(BaseModel):
    """Response after successful session upload"""
    success: bool
    session_id: str
    internal_id: str
    tool_id: str
    events_stored: int
    message: str


class SessionListResponse(BaseModel):
    """Response for listing sessions"""
    sessions: List[SessionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class SessionStatsResponse(BaseModel):
    """Aggregate statistics for sessions"""
    total_sessions: int
    total_events: int
    sessions_by_tool: Dict[str, int]
    sessions_by_editor_type: Dict[str, int]
    sessions_by_user: Dict[str, int]
    avg_session_duration_ms: Optional[float] = None
    avg_events_per_session: float
    events_by_type: Optional[Dict[str, int]] = None


# ============================================================================
# Eye Tracking Session Schemas
# ============================================================================

class EyeTrackingSessionMetadata(BaseModel):
    """Metadata for eye tracking session upload"""
    exportTime: str  # ISO timestamp
    totalPoints: int
    duration: int  # Duration in milliseconds
    trackerType: Optional[str] = "webgazer"
    screenWidth: Optional[int] = None
    screenHeight: Optional[int] = None
    calibrationPoints: Optional[int] = None


class EyeTrackingGazePoint(BaseModel):
    """Individual gaze point from eye tracker (WebGazer format)"""
    x: float
    y: float
    timestamp: int  # Unix timestamp in milliseconds


class EyeTrackingUploadRequest(BaseModel):
    """
    Complete eye tracking session upload request.
    
    This matches the JSON structure exported by the standalone eye tracking demo.
    """
    metadata: EyeTrackingSessionMetadata
    gazePoints: List[EyeTrackingGazePoint]
    
    # Optional: link to interaction recording session
    linkedSessionId: Optional[str] = None  # The session_id from interaction tracking


class EyeTrackingUploadResponse(BaseModel):
    """Response after successful eye tracking upload"""
    success: bool
    eye_tracking_session_id: str
    gaze_points_stored: int
    linked_recording_session_id: Optional[str] = None
    message: str


class EyeTrackingSessionSummary(BaseModel):
    """Summary of an eye tracking session"""
    id: str
    session_id: str
    recording_session_id: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_gaze_points: int
    total_fixations: int
    avg_confidence: Optional[float] = None
    tracker_type: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class EyeTrackingSessionDetail(BaseModel):
    """Detailed eye tracking session information"""
    id: str
    session_id: str
    recording_session_id: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_gaze_points: int
    total_fixations: int
    avg_confidence: Optional[float] = None
    tracker_type: Optional[str] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    calibration_points: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    extra_data: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# Screenshot Upload Schemas
# ============================================================================

class ScreenshotUploadRequest(BaseModel):
    """
    Screenshot upload request.
    
    Accepts a base64 encoded PNG image and optional session linkage.
    """
    imageData: str  # Base64 encoded PNG image (without data:image/png;base64, prefix)
    linkedSessionId: Optional[str] = None  # The session_id from interaction/eye tracking
    timestamp: Optional[str] = None  # ISO timestamp when screenshot was taken
    description: Optional[str] = None  # Optional description


class ScreenshotUploadResponse(BaseModel):
    """Response after successful screenshot upload"""
    success: bool
    filename: str
    filepath: str
    linked_session_id: Optional[str] = None
    message: str


# ============================================================================
# Common GLSP Event Types (for reference - not enforced)
# ============================================================================

# These are common across GLSP tools but not enforced by the API
COMMON_EVENT_TYPES = [
    # Session events
    "session_start",
    "session_end",
    "session_pause",
    "session_resume",
    
    # Element interactions
    "element_create",
    "element_select",
    "element_delete",
    "element_move",
    "element_resize",
    "element_edit",
    
    # Property changes
    "property_change",
    
    # View changes
    "viewport_change",
    "zoom_change",
    "scroll",
    
    # File operations
    "file_open",
    "file_save",
    "file_close",
    "text_edit",
    
    # Tool palette
    "tool_select",
    "palette_open",
    
    # Eye tracking
    "eye_tracking_start",
    "eye_tracking_stop",
    "eye_tracking_calibrate",
    
    # Mouse events
    "mouse_click",
    "mouse_move",
    "mouse_drag",
    
    # Keyboard events
    "key_press",
    "shortcut",
]

# Common GLSP action kinds (for reference - not enforced)
COMMON_EVENT_KINDS = [
    "createNode",
    "createEdge",
    "elementSelected",
    "changeBounds",
    "applyLabelEdit",
    "updateElementProperty",
    "setViewport",
    "center",
    "fit",
    "compound",
    "deleteElement",
]

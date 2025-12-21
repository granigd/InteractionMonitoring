"""
Database models for GLSP diagram interaction recording sessions.

Generic design to support any GLSP-based modeling tool:
- bigUML (UML diagrams)
- BPMN editors
- ER diagram editors
- Any other GLSP-based tool

Designed to support:
- Recording session metadata
- Individual interaction events (clicks, creates, selects, etc.)
- Eye-tracking gaze point data
- Clickstream analysis and nearest neighbor queries
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text,
    TIMESTAMP, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship, declarative_base

# SQLAlchemy Base for all models
Base = declarative_base()


class RecordingSession(Base):
    """
    Main recording session table.
    
    Stores metadata about a complete interaction recording session,
    including tool info, editor type, user info, and timing data.
    
    Generic for any GLSP tool.
    """
    __tablename__ = "recording_sessions"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Session identification (from frontend)
    session_id = Column(String(255), unique=True, nullable=False, index=True)
    
    # Tool identification - which GLSP tool created this session
    tool_id = Column(String(100), nullable=False, index=True, default="unknown")  # e.g., "bigUML", "bpmn-glsp", "er-glsp"
    tool_version = Column(String(50), nullable=True)  # e.g., "0.6.3"
    
    # Editor/Diagram information (generic)
    editor_type = Column(String(100), nullable=True, index=True)  # e.g., "activity", "class", "bpmn", "er"
    model_file = Column(String(255), nullable=True)  # Filename of the model file
    model_file_path = Column(Text, nullable=True)  # Full path to the model file
    
    # User information
    user_name = Column(String(255), nullable=True, index=True)
    workspace = Column(String(255), nullable=True)
    
    # Timing
    start_time = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    end_time = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)  # Computed duration in milliseconds
    
    # Statistics
    total_events = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Additional data as JSON (for extensibility - tool-specific metadata)
    extra_data = Column(JSONB, nullable=True)
    
    # Relationships
    events = relationship("InteractionEvent", back_populates="session", cascade="all, delete-orphan", lazy="dynamic")
    gaze_points = relationship("GazePoint", back_populates="session", cascade="all, delete-orphan", lazy="dynamic")
    eye_tracking_sessions = relationship("EyeTrackingSession", back_populates="recording_session", lazy="dynamic")
    
    # Indexes for common queries
    __table_args__ = (
        Index('ix_recording_sessions_tool_editor', 'tool_id', 'editor_type'),
        Index('ix_recording_sessions_tool_user', 'tool_id', 'user_name'),
        Index('ix_recording_sessions_time_range', 'start_time', 'end_time'),
    )


class InteractionEvent(Base):
    """
    Individual interaction events within a recording session.
    
    Stores each user action (click, create, select, etc.) with full
    event data for replay and analysis.
    
    Generic for any GLSP tool - the data field stores tool-specific details.
    """
    __tablename__ = "interaction_events"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign key to session
    session_id = Column(UUID(as_uuid=True), ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Event timing (high precision for clickstream analysis)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)  # Order within session
    
    # Event classification (GLSP-generic)
    event_type = Column(String(50), nullable=False, index=True)  # e.g., "element_create", "element_select"
    event_kind = Column(String(100), nullable=True, index=True)  # e.g., "createNode", "elementSelected"
    
    # Element information (denormalized for query performance)
    element_id = Column(String(255), nullable=True, index=True)  # Primary element involved
    element_type = Column(String(255), nullable=True, index=True)  # e.g., "ACTIVITY__OpaqueAction", "BPMNTask"
    
    # Position data (for spatial analysis)
    position_x = Column(Float, nullable=True)
    position_y = Column(Float, nullable=True)
    
    # Full event data as JSON (for complete replay - tool-specific)
    data = Column(JSONB, nullable=False)
    
    # Relationship
    session = relationship("RecordingSession", back_populates="events")
    
    # Indexes for analysis queries
    __table_args__ = (
        Index('ix_interaction_events_session_seq', 'session_id', 'sequence_number'),
        Index('ix_interaction_events_session_time', 'session_id', 'timestamp'),
        Index('ix_interaction_events_element', 'session_id', 'element_id'),
        Index('ix_interaction_events_type_kind', 'event_type', 'event_kind'),
    )


class GazePoint(Base):
    """
    Eye-tracking gaze point data.
    
    Stores individual gaze samples with high temporal precision
    for correlation with interaction events and spatial analysis.
    
    Completely tool-agnostic.
    """
    __tablename__ = "gaze_points"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign key to session (legacy - for backward compatibility)
    session_id = Column(UUID(as_uuid=True), ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Foreign key to eye tracking session (new - preferred)
    eye_tracking_session_id = Column(UUID(as_uuid=True), ForeignKey("eye_tracking_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Timing (high precision - microseconds matter for eye tracking)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    
    # Gaze position (screen coordinates)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    
    # Optional: normalized coordinates (0-1 range)
    x_normalized = Column(Float, nullable=True)
    y_normalized = Column(Float, nullable=True)
    
    # Eye tracking quality metrics
    pupil_diameter = Column(Float, nullable=True)  # Pupil size (cognitive load indicator)
    confidence = Column(Float, nullable=True)      # Tracking confidence/validity
    
    # Fixation grouping (computed post-hoc)
    fixation_id = Column(Integer, nullable=True, index=True)
    is_fixation = Column(Boolean, nullable=True)  # True if part of fixation, False if saccade
    
    # Which eye(s) contributed to this sample
    eye = Column(String(10), nullable=True)  # 'left', 'right', 'both'
    
    # Raw data from eye tracker (for debugging/reprocessing)
    raw_data = Column(JSONB, nullable=True)
    
    # Relationships
    session = relationship("RecordingSession", back_populates="gaze_points")
    eye_tracking_session = relationship("EyeTrackingSession", back_populates="gaze_points")
    
    # Indexes optimized for spatial queries and time-series analysis
    __table_args__ = (
        Index('ix_gaze_points_session_seq', 'session_id', 'sequence_number'),
        Index('ix_gaze_points_session_time', 'session_id', 'timestamp'),
        Index('ix_gaze_points_fixation', 'session_id', 'fixation_id'),
        Index('ix_gaze_points_eye_tracking_session', 'eye_tracking_session_id'),
        # Spatial index for nearest neighbor queries (requires PostGIS or manual GIST)
        Index('ix_gaze_points_position', 'x', 'y'),
    )


class EyeTrackingSession(Base):
    """
    Eye-tracking session metadata.
    
    Can be linked to a RecordingSession for combined interaction + eye-tracking analysis,
    or can exist as a standalone eye-tracking session.
    """
    __tablename__ = "eye_tracking_sessions"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Link to interaction recording session (optional)
    recording_session_id = Column(UUID(as_uuid=True), ForeignKey("recording_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Eye tracking session identification
    session_id = Column(String(255), nullable=False, index=True)
    
    # Timing
    start_time = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    end_time = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    # Statistics
    total_gaze_points = Column(Integer, default=0)
    total_fixations = Column(Integer, default=0)
    avg_confidence = Column(Float, nullable=True)
    
    # Metadata
    tracker_type = Column(String(100), nullable=True)  # e.g., "webgazer", "tobii", "eyelink"
    screen_width = Column(Integer, nullable=True)
    screen_height = Column(Integer, nullable=True)
    calibration_points = Column(Integer, nullable=True)
    
    # Upload metadata
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    extra_data = Column(JSONB, nullable=True)
    
    # Relationships
    recording_session = relationship("RecordingSession", back_populates="eye_tracking_sessions")
    gaze_points = relationship("GazePoint", back_populates="eye_tracking_session", cascade="all, delete-orphan", lazy="dynamic")


class ClickstreamSegment(Base):
    """
    Pre-computed clickstream segments for analysis.
    
    Stores sequences of related events for pattern mining
    and behavioral analysis.
    
    Tool-agnostic.
    """
    __tablename__ = "clickstream_segments"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign key to session
    session_id = Column(UUID(as_uuid=True), ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Segment boundaries
    start_sequence = Column(Integer, nullable=False)
    end_sequence = Column(Integer, nullable=False)
    start_time = Column(TIMESTAMP(timezone=True), nullable=False)
    end_time = Column(TIMESTAMP(timezone=True), nullable=False)
    
    # Segment classification
    segment_type = Column(String(100), nullable=True, index=True)  # e.g., "element_creation_flow"
    
    # Event sequence summary
    event_sequence = Column(ARRAY(String), nullable=True)  # List of event types in order
    event_count = Column(Integer, nullable=False)
    
    # Computed metrics
    duration_ms = Column(Integer, nullable=True)
    
    # Pattern matching
    pattern_hash = Column(String(64), nullable=True, index=True)  # Hash of event sequence for pattern matching
    
    # Metadata
    extra_data = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('ix_clickstream_segments_session_seq', 'session_id', 'start_sequence'),
    )

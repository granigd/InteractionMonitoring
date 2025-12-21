-- Migration: 001_create_sessions_tables.sql
-- Description: Create tables for GLSP diagram interaction recording sessions
-- Generic design supporting any GLSP-based tool (bigUML, BPMN, ER, etc.)

-- ============================================================================
-- Recording Sessions Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS recording_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(255) UNIQUE NOT NULL,
    
    -- Tool identification
    tool_id VARCHAR(100) NOT NULL DEFAULT 'unknown',
    tool_version VARCHAR(50),
    
    -- Editor/Model information (generic)
    editor_type VARCHAR(100),
    model_file VARCHAR(255),
    model_file_path TEXT,
    
    -- User information
    user_name VARCHAR(255),
    workspace VARCHAR(255),
    
    -- Timing
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    total_events INTEGER DEFAULT 0,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    extra_data JSONB
);

-- Indexes for recording_sessions
CREATE INDEX IF NOT EXISTS ix_recording_sessions_session_id ON recording_sessions(session_id);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_tool_id ON recording_sessions(tool_id);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_editor_type ON recording_sessions(editor_type);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_user_name ON recording_sessions(user_name);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_start_time ON recording_sessions(start_time);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_tool_editor ON recording_sessions(tool_id, editor_type);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_tool_user ON recording_sessions(tool_id, user_name);
CREATE INDEX IF NOT EXISTS ix_recording_sessions_time_range ON recording_sessions(start_time, end_time);

-- ============================================================================
-- Interaction Events Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS interaction_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES recording_sessions(id) ON DELETE CASCADE,
    
    -- Timing
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    sequence_number INTEGER NOT NULL,
    
    -- Event classification
    event_type VARCHAR(50) NOT NULL,
    event_kind VARCHAR(100),
    
    -- Element information (denormalized)
    element_id VARCHAR(255),
    element_type VARCHAR(255),
    
    -- Position data
    position_x FLOAT,
    position_y FLOAT,
    
    -- Full event data
    data JSONB NOT NULL
);

-- Indexes for interaction_events
CREATE INDEX IF NOT EXISTS ix_interaction_events_session_id ON interaction_events(session_id);
CREATE INDEX IF NOT EXISTS ix_interaction_events_timestamp ON interaction_events(timestamp);
CREATE INDEX IF NOT EXISTS ix_interaction_events_event_type ON interaction_events(event_type);
CREATE INDEX IF NOT EXISTS ix_interaction_events_event_kind ON interaction_events(event_kind);
CREATE INDEX IF NOT EXISTS ix_interaction_events_element_id ON interaction_events(element_id);
CREATE INDEX IF NOT EXISTS ix_interaction_events_element_type ON interaction_events(element_type);
CREATE INDEX IF NOT EXISTS ix_interaction_events_session_seq ON interaction_events(session_id, sequence_number);
CREATE INDEX IF NOT EXISTS ix_interaction_events_session_time ON interaction_events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_interaction_events_session_element ON interaction_events(session_id, element_id);
CREATE INDEX IF NOT EXISTS ix_interaction_events_type_kind ON interaction_events(event_type, event_kind);

-- ============================================================================
-- Gaze Points Table (Eye-tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS gaze_points (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES recording_sessions(id) ON DELETE CASCADE,
    
    -- Timing
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    sequence_number INTEGER NOT NULL,
    
    -- Position (screen coordinates)
    x FLOAT NOT NULL,
    y FLOAT NOT NULL,
    
    -- Normalized coordinates (0-1)
    x_normalized FLOAT,
    y_normalized FLOAT,
    
    -- Quality metrics
    pupil_diameter FLOAT,
    confidence FLOAT,
    
    -- Fixation grouping
    fixation_id INTEGER,
    is_fixation BOOLEAN,
    
    -- Eye source
    eye VARCHAR(10),
    
    -- Raw data
    raw_data JSONB
);

-- Indexes for gaze_points
CREATE INDEX IF NOT EXISTS ix_gaze_points_session_id ON gaze_points(session_id);
CREATE INDEX IF NOT EXISTS ix_gaze_points_timestamp ON gaze_points(timestamp);
CREATE INDEX IF NOT EXISTS ix_gaze_points_session_seq ON gaze_points(session_id, sequence_number);
CREATE INDEX IF NOT EXISTS ix_gaze_points_session_time ON gaze_points(session_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_gaze_points_fixation ON gaze_points(session_id, fixation_id);
CREATE INDEX IF NOT EXISTS ix_gaze_points_position ON gaze_points(x, y);

-- ============================================================================
-- Clickstream Segments Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS clickstream_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES recording_sessions(id) ON DELETE CASCADE,
    
    -- Segment boundaries
    start_sequence INTEGER NOT NULL,
    end_sequence INTEGER NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Classification
    segment_type VARCHAR(100),
    
    -- Event sequence
    event_sequence TEXT[],
    event_count INTEGER NOT NULL,
    duration_ms INTEGER,
    
    -- Pattern matching
    pattern_hash VARCHAR(64),
    
    -- Metadata
    extra_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for clickstream_segments
CREATE INDEX IF NOT EXISTS ix_clickstream_segments_session_id ON clickstream_segments(session_id);
CREATE INDEX IF NOT EXISTS ix_clickstream_segments_segment_type ON clickstream_segments(segment_type);
CREATE INDEX IF NOT EXISTS ix_clickstream_segments_pattern_hash ON clickstream_segments(pattern_hash);
CREATE INDEX IF NOT EXISTS ix_clickstream_segments_session_seq ON clickstream_segments(session_id, start_sequence);

-- ============================================================================
-- Update Trigger for recording_sessions.updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_recording_sessions_updated_at ON recording_sessions;
CREATE TRIGGER update_recording_sessions_updated_at
    BEFORE UPDATE ON recording_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

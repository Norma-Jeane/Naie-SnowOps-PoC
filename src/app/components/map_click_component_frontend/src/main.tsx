import React from "react";
import ReactDOM from "react-dom/client";
import { Streamlit, withStreamlitConnection } from "streamlit-component-lib";
import MapClickComponent from "./MapClickComponent";

type ViewStateInput = {
  lat: number;
  lon: number;
  zoom: number;
};

type PointInput = {
  lat: number;
  lon: number;
};

type RouteCycleSegment = {
  segment_order?: number | string | null;
  segment_type?: string | null;
  path: PointInput[];
  pass_from_node?: number | string | null;
  pass_to_node?: number | string | null;
  u?: number | string | null;
  v?: number | string | null;
  key?: number | string | null;
  edge_id?: EdgeId | null;
  length?: number | null;
  undirected_edge_key?: string | null;
  edge_group_key?: string | null;
  lane_group_key?: string | null;
  edge_direction?: "forward" | "reverse" | null;
  pass_direction_kind?: string | null;
  pass_direction_value?: string | null;
  edge_repeat_count: number;
  edge_repeat_index: number;
  direction_pass_count?: number;
  direction_pass_index?: number;
  lane_count?: number;
  lane_index?: number;
  offset_side?: "left" | null;
  offset_lane: number;
  original_segment_orders?: Array<number | string | null>;
  original_segment_types?: Array<string | null>;
  original_pass_from_nodes?: Array<number | string | null>;
  original_pass_to_nodes?: Array<number | string | null>;
};

type RouteCycleGuide = {
  kind: "route_cycle";
  path: PointInput[];
  segments?: RouteCycleSegment[];
  raw_pass_segments?: RouteCycleSegment[];
  start: PointInput;
  end: PointInput;
  first_segment_order?: number | string | null;
  last_segment_order?: number | string | null;
  segment_count: number;
  display_segment_count?: number;
  raw_pass_segment_count?: number;
  included_segment_types: string[];
};

type ComponentArgs = {
  initial_view_state: ViewStateInput;
  current_start_point: PointInput | null;
  candidate_start_point: PointInput | null;
  reset_view_nonce: number;
  roads_geojson?: GeoJSON.FeatureCollection | null;
  road_state?: RoadState | null;
  route_geojson?: GeoJSON.FeatureCollection | null;
  route_cycle_guide?: RouteCycleGuide | null;
  show_route_cycle_guide?: boolean;
  debug_mode?: boolean;
  pending_sync_nonce?: number;
  line_styles?: Record<string, unknown> | null;
  height?: number;
};

type EdgeId = {
  u: string;
  v: string;
  key: string;
};

type RoadInstructionState = "none" | "exclude" | "conditional" | "include" | "include_failed";

type RoadInstructionOverride = {
  edge_id?: EdgeId | null;
  instruction_state?: RoadInstructionState | null;
};

type RoadState = {
  roads_geojson_version?: string | null;
  route_geojson_version?: string | null;
  selected_edge_id?: EdgeId | null;
  instruction_sync_ack_nonce?: number | null;
  instructions?: RoadInstructionOverride[] | null;
  failed_partial_edge_ids?: EdgeId[] | null;
  after_black_clear_edge_ids?: EdgeId[] | null;
  suppressed_base_edge_ids?: EdgeId[] | null;
};

type StartPointSetEvent = {
  event_type: "start_point_set";
  lat: number;
  lon: number;
};

type RoadSelectEvent = {
  event_type: "road_select";
  edge_id: EdgeId;
};

type RoadToggleEvent = {
  event_type: "road_toggle";
  edge_id: EdgeId;
};

type RoadInstructionsSyncEvent = {
  event_type: "road_instructions_sync";
  instructions: Array<{
    edge_id: EdgeId;
    instruction_state: RoadInstructionState;
  }>;
  pending_count: number;
};

type RoadClearEvent = {
  event_type: "road_clear";
};

type StartPointRestoreEvent = {
  event_type: "start_point_restore";
};

type ComponentEvent =
  | StartPointSetEvent
  | RoadSelectEvent
  | RoadToggleEvent
  | RoadInstructionsSyncEvent
  | RoadClearEvent
  | StartPointRestoreEvent;

type ErrorBoundaryState = {
  message: string | null;
  stack: string | null;
  componentStack: string | null;
  source: "react" | "window" | "promise" | null;
};

function normalizeUnknownError(value: unknown): { message: string; stack: string | null } {
  if (value instanceof Error) {
    return {
      message: value.message || value.name || "Unknown error",
      stack: value.stack ?? null,
    };
  }

  if (typeof value === "string" && value.trim() !== "") {
    return { message: value, stack: null };
  }

  try {
    return { message: JSON.stringify(value), stack: null };
  } catch {
    return { message: String(value), stack: null };
  }
}

class ComponentErrorBoundary extends React.Component<
  { children: React.ReactNode },
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = {
    message: null,
    stack: null,
    componentStack: null,
    source: null,
  };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      message: error.message || error.name || "Unknown React error",
      stack: error.stack ?? null,
      componentStack: null,
      source: "react",
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error("[main.tsx] Component runtime error", error, errorInfo);
    this.setState({
      message: error.message || error.name || "Unknown React error",
      stack: error.stack ?? null,
      componentStack: errorInfo.componentStack || null,
      source: "react",
    });
  }

  componentDidMount(): void {
    window.addEventListener("error", this.handleWindowError);
    window.addEventListener("unhandledrejection", this.handleUnhandledRejection);
  }

  componentWillUnmount(): void {
    window.removeEventListener("error", this.handleWindowError);
    window.removeEventListener("unhandledrejection", this.handleUnhandledRejection);
  }

  private handleWindowError = (event: ErrorEvent): void => {
    const normalized = normalizeUnknownError(event.error ?? event.message);
    console.error("[main.tsx] window error", event.error ?? event.message);
    this.setState({
      message: normalized.message,
      stack: normalized.stack,
      componentStack: null,
      source: "window",
    });
  };

  private handleUnhandledRejection = (event: PromiseRejectionEvent): void => {
    const normalized = normalizeUnknownError(event.reason);
    console.error("[main.tsx] unhandled rejection", event.reason);
    this.setState({
      message: normalized.message,
      stack: normalized.stack,
      componentStack: null,
      source: "promise",
    });
  };

  render(): React.ReactNode {
    if (!this.state.message) {
      return this.props.children;
    }

    return (
      <div
        style={{
          width: "100%",
          background: "#fff7ed",
          border: "1px solid #fdba74",
          borderRadius: "8px",
          padding: "16px",
          boxSizing: "border-box",
          color: "#7c2d12",
        }}
      >
        <div style={{ fontWeight: 700, fontSize: "20px", marginBottom: "12px" }}>
          Component Runtime Error
        </div>
        <div style={{ marginBottom: "8px", fontSize: "14px" }}>
          source: <strong>{this.state.source ?? "unknown"}</strong>
        </div>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            background: "#ffedd5",
            borderRadius: "6px",
            padding: "12px",
            margin: 0,
            marginBottom: "12px",
            fontSize: "13px",
          }}
        >
          {this.state.message}
        </pre>
        {this.state.stack ? (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "#fff",
              borderRadius: "6px",
              padding: "12px",
              margin: 0,
              marginBottom: "12px",
              fontSize: "12px",
              border: "1px solid #fed7aa",
            }}
          >
            {this.state.stack}
          </pre>
        ) : null}
        {this.state.componentStack ? (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "#fff",
              borderRadius: "6px",
              padding: "12px",
              margin: 0,
              fontSize: "12px",
              border: "1px solid #fed7aa",
            }}
          >
            {this.state.componentStack}
          </pre>
        ) : null}
      </div>
    );
  }
}

function normalizeNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  if (Number.isFinite(parsed)) {
    return parsed;
  }
  return fallback;
}

function normalizePoint(value: unknown): PointInput | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value !== "object") {
    return null;
  }

  const obj = value as Record<string, unknown>;
  const lat = Number(obj.lat);
  const lon = Number(obj.lon);

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null;
  }

  return { lat, lon };
}

function normalizePointArray(value: unknown): PointInput[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (Array.isArray(item) && item.length >= 2) {
        const lon = Number(item[0]);
        const lat = Number(item[1]);
        if (Number.isFinite(lon) && Number.isFinite(lat)) {
          return { lat, lon };
        }
      }

      if (typeof item === "object" && item !== null) {
        const point = item as Record<string, unknown>;
        const lat = Number(point.lat);
        const lon = Number(point.lon);
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          return { lat, lon };
        }
      }

      return null;
    })
    .filter((item): item is PointInput => item !== null);
}

function normalizeOrderArray(value: unknown): Array<number | string | null> {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (typeof item === "string" || typeof item === "number" || item === null) {
        return item;
      }
      return null;
    })
    .filter((item): item is number | string | null => item !== undefined);
}

function normalizeEdgeId(value: unknown): EdgeId | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const obj = value as Record<string, unknown>;
  if (
    (typeof obj.u === "string" || typeof obj.u === "number") &&
    (typeof obj.v === "string" || typeof obj.v === "number") &&
    (typeof obj.key === "string" || typeof obj.key === "number")
  ) {
    return {
      u: String(obj.u),
      v: String(obj.v),
      key: String(obj.key),
    };
  }
  return null;
}

function normalizeRouteCycleSegment(value: unknown): RouteCycleSegment | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }

  const segment = value as Record<string, unknown>;
  const segmentPath = normalizePointArray(segment.path);
  if (segmentPath.length < 2) {
    return null;
  }

  return {
    segment_order:
      typeof segment.segment_order === "string" || typeof segment.segment_order === "number"
        ? segment.segment_order
        : null,
    segment_type: typeof segment.segment_type === "string" ? segment.segment_type : null,
    path: segmentPath,
    pass_from_node:
      typeof segment.pass_from_node === "string" || typeof segment.pass_from_node === "number"
        ? segment.pass_from_node
        : null,
    pass_to_node:
      typeof segment.pass_to_node === "string" || typeof segment.pass_to_node === "number"
        ? segment.pass_to_node
        : null,
    u: typeof segment.u === "string" || typeof segment.u === "number" ? segment.u : null,
    v: typeof segment.v === "string" || typeof segment.v === "number" ? segment.v : null,
    key: typeof segment.key === "string" || typeof segment.key === "number" ? segment.key : null,
    edge_id: normalizeEdgeId(segment.edge_id),
    length: Number.isFinite(Number(segment.length)) ? Number(segment.length) : null,
    undirected_edge_key:
      typeof segment.undirected_edge_key === "string" ? segment.undirected_edge_key : null,
    edge_group_key: typeof segment.edge_group_key === "string" ? segment.edge_group_key : null,
    lane_group_key: typeof segment.lane_group_key === "string" ? segment.lane_group_key : null,
    edge_direction:
      segment.edge_direction === "forward" || segment.edge_direction === "reverse"
        ? segment.edge_direction
        : null,
    pass_direction_kind:
      typeof segment.pass_direction_kind === "string" ? segment.pass_direction_kind : null,
    pass_direction_value:
      typeof segment.pass_direction_value === "string" ? segment.pass_direction_value : null,
    edge_repeat_count: Math.trunc(normalizeNumber(segment.edge_repeat_count, 1)),
    edge_repeat_index: Math.trunc(normalizeNumber(segment.edge_repeat_index, 0)),
    direction_pass_count: Math.trunc(normalizeNumber(segment.direction_pass_count, 1)),
    direction_pass_index: Math.trunc(normalizeNumber(segment.direction_pass_index, 0)),
    lane_count: Math.trunc(normalizeNumber(segment.lane_count, 1)),
    lane_index: Math.trunc(normalizeNumber(segment.lane_index, 0)),
    offset_side: segment.offset_side === "left" ? "left" : null,
    offset_lane: Math.trunc(normalizeNumber(segment.offset_lane, 0)),
    original_segment_orders: normalizeOrderArray(segment.original_segment_orders),
    original_segment_types: Array.isArray(segment.original_segment_types)
      ? segment.original_segment_types.map((item) => (typeof item === "string" ? item : null))
      : [],
    original_pass_from_nodes: normalizeOrderArray(segment.original_pass_from_nodes),
    original_pass_to_nodes: normalizeOrderArray(segment.original_pass_to_nodes),
  };
}

function normalizeRouteCycleGuide(value: unknown): RouteCycleGuide | null {
  if (value === null || value === undefined || typeof value !== "object") {
    return null;
  }

  const obj = value as Record<string, unknown>;
  const path = normalizePointArray(obj.path);

  if (path.length < 2) {
    return null;
  }

  const segments = Array.isArray(obj.segments)
    ? obj.segments
        .map((item) => normalizeRouteCycleSegment(item))
        .filter((item): item is RouteCycleSegment => item !== null)
    : [];
  const raw_pass_segments = Array.isArray(obj.raw_pass_segments)
    ? obj.raw_pass_segments
        .map((item) => normalizeRouteCycleSegment(item))
        .filter((item): item is RouteCycleSegment => item !== null)
    : [];
  const included_segment_types = Array.isArray(obj.included_segment_types)
    ? obj.included_segment_types.filter((item): item is string => typeof item === "string")
    : [];

  return {
    kind: "route_cycle",
    path,
    segments,
    raw_pass_segments,
    start: normalizePoint(obj.start) ?? path[0],
    end: normalizePoint(obj.end) ?? path[path.length - 1],
    first_segment_order:
      typeof obj.first_segment_order === "string" || typeof obj.first_segment_order === "number"
        ? obj.first_segment_order
        : null,
    last_segment_order:
      typeof obj.last_segment_order === "string" || typeof obj.last_segment_order === "number"
        ? obj.last_segment_order
        : null,
    segment_count: Math.trunc(normalizeNumber(obj.segment_count, 0)),
    display_segment_count: Math.trunc(normalizeNumber(obj.display_segment_count, segments.length)),
    raw_pass_segment_count: Math.trunc(
      normalizeNumber(obj.raw_pass_segment_count, raw_pass_segments.length),
    ),
    included_segment_types,
  };
}

function normalizeArgs(rawArgs: Record<string, unknown>): ComponentArgs {
  const initialRaw = (rawArgs.initial_view_state ?? {}) as Record<string, unknown>;

  return {
    initial_view_state: {
      lat: normalizeNumber(initialRaw.lat, 43.426),
      lon: normalizeNumber(initialRaw.lon, 141.886),
      zoom: normalizeNumber(initialRaw.zoom, 12),
    },
    current_start_point: normalizePoint(rawArgs.current_start_point),
    candidate_start_point: normalizePoint(rawArgs.candidate_start_point),
    reset_view_nonce: Math.trunc(normalizeNumber(rawArgs.reset_view_nonce, 0)),
    roads_geojson: (rawArgs.roads_geojson as GeoJSON.FeatureCollection | null | undefined) ?? null,
    road_state: (rawArgs.road_state as RoadState | null | undefined) ?? null,
    route_geojson: (rawArgs.route_geojson as GeoJSON.FeatureCollection | null | undefined) ?? null,
    route_cycle_guide: normalizeRouteCycleGuide(rawArgs.route_cycle_guide),
    show_route_cycle_guide: rawArgs.show_route_cycle_guide !== false,
    debug_mode: rawArgs.debug_mode === true,
    pending_sync_nonce: Math.trunc(normalizeNumber(rawArgs.pending_sync_nonce, 0)),
    line_styles: (rawArgs.line_styles as Record<string, unknown> | null | undefined) ?? null,
    height: Math.trunc(normalizeNumber(rawArgs.height, 600)),
  };
}

type StreamlitComponentProps = {
  args: Record<string, unknown>;
};

function ComponentRoot(props: StreamlitComponentProps): React.ReactElement {
  const args = normalizeArgs(props.args);
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const target = containerRef.current;
    if (!target) {
      return;
    }

    let animationFrameId = 0;

    const updateFrameHeight = (): void => {
      const baseHeight = args.height ?? 600;
      const rectHeight = Math.ceil(target.getBoundingClientRect().height);
      Streamlit.setFrameHeight(Math.max(baseHeight, rectHeight));
    };

    const scheduleUpdateFrameHeight = (): void => {
      window.cancelAnimationFrame(animationFrameId);
      animationFrameId = window.requestAnimationFrame(updateFrameHeight);
    };

    scheduleUpdateFrameHeight();

    const resizeObserver = new ResizeObserver(() => {
      scheduleUpdateFrameHeight();
    });
    resizeObserver.observe(target);

    window.addEventListener("resize", scheduleUpdateFrameHeight);

    return () => {
      window.removeEventListener("resize", scheduleUpdateFrameHeight);
      resizeObserver.disconnect();
      window.cancelAnimationFrame(animationFrameId);
    };
  }, [args.height]);

  const handleEvent = React.useCallback((event: ComponentEvent) => {
    const payload = JSON.parse(JSON.stringify(event));
    console.log("[main.tsx:road-select] handleEvent", payload);
    Streamlit.setComponentValue(payload);
  }, []);

  return (
    <div ref={containerRef}>
      <ComponentErrorBoundary>
        <MapClickComponent
          initialViewState={{
            lat: args.initial_view_state.lat,
            lon: args.initial_view_state.lon,
            zoom: args.initial_view_state.zoom,
          }}
          currentStartPoint={args.current_start_point}
          candidateStartPoint={args.candidate_start_point}
          resetViewNonce={args.reset_view_nonce}
          roadsGeojson={args.roads_geojson ?? null}
          roadState={args.road_state ?? null}
          routeGeojson={args.route_geojson ?? null}
          routeCycleGuide={args.route_cycle_guide ?? null}
          showRouteCycleGuide={args.show_route_cycle_guide ?? true}
          debugMode={args.debug_mode ?? false}
          pendingSyncNonce={args.pending_sync_nonce ?? 0}
          lineStyles={args.line_styles ?? null}
          height={args.height ?? 600}
          onEvent={handleEvent}
        />
      </ComponentErrorBoundary>
    </div>
  );
}

const ConnectedComponent = withStreamlitConnection(ComponentRoot);

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found.");
}

const root = ReactDOM.createRoot(rootElement);
root.render(<ConnectedComponent />);

import React, { useEffect, useMemo, useRef, useState } from "react";
import MapComponent, {
  Layer,
  NavigationControl,
  Source,
  type LayerProps,
  type MapMouseEvent,
  type MapRef,
  type ViewStateChangeEvent,
} from "react-map-gl";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

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

type EdgeId = {
  u: string;
  v: string;
  key: string;
};

type EventMapViewState = {
  lat: number;
  lon: number;
  zoom: number;
  bearing: number;
  pitch: number;
};

type EventEnvelope = {
  event_nonce: number;
  component_instance_id: string;
  map_view_state: EventMapViewState;
};

type InstructionState =
  | "none"
  | "exclude"
  | "conditional"
  | "include"
  | "include_failed";
type BaseDisplayState = "target" | "connector" | "return" | "candidate" | "non_operable";
type DiffDisplayState = "transparent" | "black" | "orange" | "magenta" | "red";
type LegacyDisplayState = "blue" | "gray";
type DisplayState = BaseDisplayState | DiffDisplayState | LegacyDisplayState | "none";

type RoadSelectEvent = EventEnvelope & {
  event_type: "road_select";
  edge_id: EdgeId;
};

type RoadToggleEvent = EventEnvelope & {
  event_type: "road_toggle";
  edge_id: EdgeId;
  display_state?: DisplayState;
  next_instruction_state?: InstructionState;
};

type RoadInstructionsSyncEvent = EventEnvelope & {
  event_type: "road_instructions_sync";
  instructions: Array<{
    edge_id: EdgeId;
    instruction_state: InstructionState;
  }>;
  pending_count: number;
  sync_nonce: number;
};

type RoadClearEvent = EventEnvelope & {
  event_type: "road_clear";
};

type StartPointSetEvent = EventEnvelope & {
  event_type: "start_point_set";
  lat: number;
  lon: number;
};

type StartPointRestoreEvent = EventEnvelope & {
  event_type: "start_point_restore";
};

type StartPointRestoreToRecalculationBaselineEvent = EventEnvelope & {
  event_type: "start_point_restore_to_recalculation_baseline";
};

type MapViewUpdateEvent = EventEnvelope & {
  event_type: "map_view_update";
};

type ComponentEvent =
  | StartPointSetEvent
  | RoadSelectEvent
  | RoadToggleEvent
  | RoadInstructionsSyncEvent
  | RoadClearEvent
  | StartPointRestoreEvent
  | StartPointRestoreToRecalculationBaselineEvent
  | MapViewUpdateEvent;

type Props = {
  initialViewState: ViewStateInput;
  currentStartPoint: PointInput | null;
  candidateStartPoint: PointInput | null;
  resetViewNonce: number;
  roadsGeojson?: GeoJSON.FeatureCollection | null;
  roadState?: RoadState | null;
  routeGeojson?: GeoJSON.FeatureCollection | null;
  routeCycleGuide?: RouteCycleGuide | null;
  showRouteCycleGuide?: boolean;
  debugMode?: boolean;
  pendingSyncNonce?: number;
  lineStyles?: unknown;
  height?: number;
  onEvent: (event: ComponentEvent) => void;
};

type RoadOption = {
  label: string;
  edgeId: EdgeId;
  instructionState: InstructionState;
  noInstructionCycleHint?: "after_black_clear";
  baseDisplayState: BaseDisplayState;
  diffDisplayState: DiffDisplayState;
  displayState: DisplayState;
  isExcluded: boolean;
  isOnCurrentRoute: boolean;
  isSelected: boolean;
};

type RoadStateInstruction = {
  edge_id?: EdgeId | null;
  instruction_state?: InstructionState | null;
};

type RoadState = {
  roads_geojson_version?: string | null;
  route_geojson_version?: string | null;
  selected_edge_id?: EdgeId | null;
  instruction_sync_ack_nonce?: number | null;
  instructions?: RoadStateInstruction[] | null;
  failed_partial_edge_ids?: EdgeId[] | null;
  after_black_clear_edge_ids?: EdgeId[] | null;
  suppressed_base_edge_ids?: EdgeId[] | null;
};

type RoadStateLookup = {
  instructionByKey: Map<string, InstructionState>;
  failedPartialKeys: Set<string>;
  afterBlackClearKeys: Set<string>;
  suppressedBaseKeys: Set<string>;
  selectedRoadKey: string;
};

type RoadFeatureProperties = {
  display_kind?: unknown;
  base_display_state?: unknown;
  diff_display_state?: unknown;
  display_state?: unknown;
  is_excluded?: unknown;
  is_conditional?: unknown;
  is_included?: unknown;
  is_failed_included?: unknown;
  is_failed_partial?: unknown;
  is_base_suppressed_by_final_state?: unknown;
  is_route_suppressed_by_final_state?: unknown;
  is_on_current_route?: unknown;
  is_selected?: unknown;
  instruction_state?: unknown;
  no_instruction_cycle_hint?: unknown;
  segment_type?: unknown;
  name?: unknown;
  road_id_text?: unknown;
  u?: unknown;
  v?: unknown;
  key?: unknown;
};

type LineGeometry = GeoJSON.LineString | GeoJSON.MultiLineString;
type RoadFeature = GeoJSON.Feature<LineGeometry, RoadFeatureProperties>;

type MapViewState = {
  latitude: number;
  longitude: number;
  zoom: number;
  bearing: number;
  pitch: number;
};

type PixelPoint = {
  x: number;
  y: number;
};

type RouteCyclePixelSegment = {
  points: PixelPoint[];
  basePoints: PixelPoint[];
  edgeOffsetsPx: number[];
  edgeSegmentOrders: Array<number | string | null>;
  segmentOrder: number | string | null;
  passFromNode: number | string | null;
  passToNode: number | string | null;
  edgeRepeatCount: number;
  edgeRepeatIndex: number;
  directionPassCount: number;
  directionPassIndex: number;
  offsetLane: number;
  isRawPassSegment: boolean;
  isClosedLoop: boolean;
};

type RouteCycleGuideRun = {
  points: PixelPoint[];
  basePoints: PixelPoint[];
  edgeOffsetsPx: number[];
  edgeSegmentOrders: Array<number | string | null>;
  isRawPassRun: boolean;
  segmentOrder: number | string | null;
  firstSegmentOrder: number | string | null;
  lastSegmentOrder: number | string | null;
  firstPassFromNode: number | string | null;
  lastPassToNode: number | string | null;
  segmentIndex: number;
  edgeRepeatCount: number;
  edgeRepeatIndex: number;
  offsetLane: number;
  isClosedLoop: boolean;
};

type RouteCycleGuideJoin = {
  points: PixelPoint[];
  cubicControls?: [PixelPoint, PixelPoint];
};

type RouteCycleGuideArrow = {
  x: number;
  y: number;
  angle: number;
  points: PixelPoint[];
};

type RouteCycleGuideMarkerStyle = {
  type: "arrow";
  fillColor: string;
  strokeColor: string;
  lengthPx: number;
  widthPx: number;
};

type RouteCycleGuideMarkerLayout = {
  startPaddingPx: number;
  endPaddingPx: number;
  minRunLengthPx: number;
};

type RouteCycleGuideStyle = {
  lineColor: string;
  lineWidth: number;
  baseOffsetPx: number;
  laneOffsetPx: number;
  marker: RouteCycleGuideMarkerStyle;
  markerLayout: RouteCycleGuideMarkerLayout;
};

const DEFAULT_ROUTE_CYCLE_GUIDE_STYLE: RouteCycleGuideStyle = {
  lineColor: "#16a34a",
  lineWidth: 1.8,
  baseOffsetPx: 6,
  laneOffsetPx: 3,
  marker: {
    type: "arrow",
    fillColor: "#16a34a",
    strokeColor: "#16a34a",
    lengthPx: 14,
    widthPx: 6,
  },
  markerLayout: {
    startPaddingPx: 70,
    endPaddingPx: 36,
    minRunLengthPx: 70,
  },
};

const ROUTE_CYCLE_START_DEBUG_COLOR = "#facc15";
const ROUTE_CYCLE_ARRIVAL_DEBUG_COLOR = "#22d3ee";
const ROUTE_CYCLE_ARROW_CUMULATIVE_INTERVAL_PX = 96;
const ROUTE_CYCLE_ARROW_RUN_CONTINUITY_GAP_PX = 16;
const ROUTE_CYCLE_MIN_OFFSET_SEGMENT_LENGTH_PX = 0.75;
const ROUTE_CYCLE_OFFSET_MITER_LIMIT = 4;
const ROUTE_CYCLE_OFFSET_MITER_EDGE_LENGTH_RATIO_LIMIT = 6;
const ROUTE_CYCLE_OFFSET_MITER_EDGE_LENGTH_RATIO_MAX_SEGMENT_PX = 10;
const ROUTE_CYCLE_OFFSET_JOIN_MIN_GAP_PX = 1.25;
const ROUTE_CYCLE_BASE_JOIN_MAX_GAP_PX = 8;
const ROUTE_CYCLE_UTURN_DOT_THRESHOLD = -0.7;
const ROUTE_CYCLE_SHARP_JOIN_DOT_THRESHOLD = 0.65;
const ROUTE_CYCLE_SMOOTH_JOIN_BEZIER_MIN_HANDLE_PX = 4;
const ROUTE_CYCLE_SMOOTH_JOIN_BEZIER_MAX_HANDLE_PX = 28;
const ROUTE_CYCLE_GUIDE_MAX_PITCH_DEGREES = 0.5;

function getRouteCycleGuideLaneOffsetZoomScale(zoom: number): number {
  if (!Number.isFinite(zoom)) {
    return 1;
  }
  if (zoom <= 15.5) {
    return 1;
  }
  if (zoom >= 17.5) {
    return 1.8;
  }
  return 1 + ((zoom - 15.5) / 2) * 0.8;
}

function projectGuidePoint(map: MapRef, point: PointInput): PixelPoint | null {
  const projected = map.project([point.lon, point.lat]);
  if (!projected || !Number.isFinite(projected.x) || !Number.isFinite(projected.y)) {
    return null;
  }
  return { x: projected.x, y: projected.y };
}

function routeCycleGuideSegmentOffsetPx(
  offsetLane: number,
  edgeRepeatCount: number,
  style: RouteCycleGuideStyle,
  laneOffsetScale: number,
): number {
  const repeatedLaneOffset =
    edgeRepeatCount >= 2 ? Math.max(0, offsetLane) * style.laneOffsetPx * laneOffsetScale : 0;
  return style.baseOffsetPx + repeatedLaneOffset;
}

function routeCycleLineIntersection(
  pointA: PixelPoint,
  directionA: PixelPoint,
  pointB: PixelPoint,
  directionB: PixelPoint,
): PixelPoint | null {
  const cross = directionA.x * directionB.y - directionA.y * directionB.x;
  if (Math.abs(cross) < 1e-6) {
    return null;
  }
  const dx = pointB.x - pointA.x;
  const dy = pointB.y - pointA.y;
  const distanceA = (dx * directionB.y - dy * directionB.x) / cross;
  const x = pointA.x + directionA.x * distanceA;
  const y = pointA.y + directionA.y * distanceA;
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }
  return { x, y };
}

function averageRouteCycleOffsetPoint(
  point: PixelPoint,
  previousNormal: PixelPoint,
  previousOffsetPx: number,
  nextNormal: PixelPoint,
  nextOffsetPx: number,
): PixelPoint {
  return {
    x: point.x + (previousNormal.x * previousOffsetPx + nextNormal.x * nextOffsetPx) / 2,
    y: point.y + (previousNormal.y * previousOffsetPx + nextNormal.y * nextOffsetPx) / 2,
  };
}

function computeRouteCyclePolylineOffsetPoints(
  points: PixelPoint[],
  edgeOffsetsPx: number[],
): PixelPoint[] {
  if (points.length < 2) {
    return points;
  }

  const edgeCount = points.length - 1;
  const directions: Array<PixelPoint | null> = [];
  const normals: Array<PixelPoint | null> = [];
  const edgeLengthsPx: number[] = [];

  for (let index = 0; index < edgeCount; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy);
    edgeLengthsPx.push(length);
    if (length < ROUTE_CYCLE_MIN_OFFSET_SEGMENT_LENGTH_PX) {
      directions.push(null);
      normals.push(null);
      continue;
    }
    const direction = { x: dx / length, y: dy / length };
    directions.push(direction);
    normals.push({ x: direction.y, y: -direction.x });
  }

  const findPreviousEdgeIndex = (pointIndex: number): number | null => {
    for (let edgeIndex = Math.min(pointIndex - 1, edgeCount - 1); edgeIndex >= 0; edgeIndex -= 1) {
      if (directions[edgeIndex] && normals[edgeIndex]) {
        return edgeIndex;
      }
    }
    return null;
  };

  const findNextEdgeIndex = (pointIndex: number): number | null => {
    for (let edgeIndex = Math.max(0, pointIndex); edgeIndex < edgeCount; edgeIndex += 1) {
      if (directions[edgeIndex] && normals[edgeIndex]) {
        return edgeIndex;
      }
    }
    return null;
  };

  return points.map((point, pointIndex) => {
    const previousEdgeIndex = findPreviousEdgeIndex(pointIndex);
    const nextEdgeIndex = findNextEdgeIndex(pointIndex);
    const edgeIndex = previousEdgeIndex ?? nextEdgeIndex;
    if (edgeIndex === null) {
      return point;
    }

    if (previousEdgeIndex === null || nextEdgeIndex === null) {
      const normal = normals[edgeIndex];
      if (!normal) {
        return point;
      }
      const offsetPx = edgeOffsetsPx[edgeIndex] ?? edgeOffsetsPx[edgeOffsetsPx.length - 1] ?? 0;
      return { x: point.x + normal.x * offsetPx, y: point.y + normal.y * offsetPx };
    }

    const previousDirection = directions[previousEdgeIndex];
    const nextDirection = directions[nextEdgeIndex];
    const previousNormal = normals[previousEdgeIndex];
    const nextNormal = normals[nextEdgeIndex];
    if (!previousDirection || !nextDirection || !previousNormal || !nextNormal) {
      return point;
    }

    const previousOffsetPx = edgeOffsetsPx[previousEdgeIndex] ?? 0;
    const nextOffsetPx = edgeOffsetsPx[nextEdgeIndex] ?? previousOffsetPx;
    const previousOffsetPoint = {
      x: point.x + previousNormal.x * previousOffsetPx,
      y: point.y + previousNormal.y * previousOffsetPx,
    };
    const nextOffsetPoint = {
      x: point.x + nextNormal.x * nextOffsetPx,
      y: point.y + nextNormal.y * nextOffsetPx,
    };
    const intersection = routeCycleLineIntersection(
      previousOffsetPoint,
      previousDirection,
      nextOffsetPoint,
      nextDirection,
    );
    if (!intersection) {
      return averageRouteCycleOffsetPoint(
        point,
        previousNormal,
        previousOffsetPx,
        nextNormal,
        nextOffsetPx,
      );
    }

    const miterDistancePx = Math.hypot(intersection.x - point.x, intersection.y - point.y);
    const maxOffsetPx = Math.max(Math.abs(previousOffsetPx), Math.abs(nextOffsetPx));
    const miterLimitPx = Math.max(12, maxOffsetPx * ROUTE_CYCLE_OFFSET_MITER_LIMIT);
    const minAdjacentSegmentLengthPx = Math.min(
      edgeLengthsPx[previousEdgeIndex] ?? Infinity,
      edgeLengthsPx[nextEdgeIndex] ?? Infinity,
    );
    const shouldUseShortEdgeRatioFallback =
      minAdjacentSegmentLengthPx <= ROUTE_CYCLE_OFFSET_MITER_EDGE_LENGTH_RATIO_MAX_SEGMENT_PX;
    const miterEdgeLengthRatioLimitPx =
      minAdjacentSegmentLengthPx * ROUTE_CYCLE_OFFSET_MITER_EDGE_LENGTH_RATIO_LIMIT;
    const shouldUseMiterRatioFallback =
      shouldUseShortEdgeRatioFallback &&
      Number.isFinite(miterEdgeLengthRatioLimitPx) &&
      miterEdgeLengthRatioLimitPx > 0 &&
      miterDistancePx > miterEdgeLengthRatioLimitPx;
    if (
      !Number.isFinite(miterDistancePx) ||
      miterDistancePx > miterLimitPx ||
      shouldUseMiterRatioFallback
    ) {
      return averageRouteCycleOffsetPoint(
        point,
        previousNormal,
        previousOffsetPx,
        nextNormal,
        nextOffsetPx,
      );
    }

    return intersection;
  });
}

function buildOffsetRouteCycleGuideRuns(runs: RouteCycleGuideRun[]): RouteCycleGuideRun[] {
  return runs.map((run) => ({
    ...run,
    points: computeRouteCyclePolylineOffsetPoints(run.basePoints, run.edgeOffsetsPx),
  }));
}

function findRouteCycleRunSegmentPoints(
  runs: RouteCycleGuideRun[],
  segmentOrder: number | string | null | undefined,
): PixelPoint[] | null {
  const targetOrder = parseRouteCycleSegmentOrder(segmentOrder);
  if (targetOrder === null) {
    return null;
  }

  for (const run of runs) {
    for (let edgeIndex = 0; edgeIndex < run.edgeSegmentOrders.length; edgeIndex += 1) {
      if (parseRouteCycleSegmentOrder(run.edgeSegmentOrders[edgeIndex]) !== targetOrder) {
        continue;
      }
      const startIndex = edgeIndex;
      let endIndex = edgeIndex + 1;
      while (
        endIndex < run.edgeSegmentOrders.length &&
        parseRouteCycleSegmentOrder(run.edgeSegmentOrders[endIndex]) === targetOrder
      ) {
        endIndex += 1;
      }
      return run.points.slice(startIndex, endIndex + 1);
    }
  }

  return null;
}

function routeCycleSegmentDisplayColor(
  segmentOrder: number | string | null | undefined,
  firstOrder: number | null,
  lastOrder: number | null,
  fallbackColor: string,
): string {
  const order = parseRouteCycleSegmentOrder(segmentOrder);
  if (order !== null && firstOrder !== null && order === firstOrder) {
    return ROUTE_CYCLE_START_DEBUG_COLOR;
  }
  if (order !== null && lastOrder !== null && order === lastOrder) {
    return ROUTE_CYCLE_ARRIVAL_DEBUG_COLOR;
  }
  return fallbackColor;
}

function buildRouteCycleDisplaySegments(
  run: RouteCycleGuideRun,
  left: number,
  top: number,
  firstOrder: number | null,
  lastOrder: number | null,
  fallbackColor: string,
): Array<{
  pointText: string;
  edgeRepeatCount: number;
  edgeRepeatIndex: number;
  offsetLane: number;
  color: string;
}> {
  if (run.points.length < 2) {
    return [];
  }

  const segments: Array<{
    points: PixelPoint[];
    color: string;
  }> = [];

  let currentPoints = [run.points[0]];
  let currentColor = routeCycleSegmentDisplayColor(
    run.edgeSegmentOrders[0],
    firstOrder,
    lastOrder,
    fallbackColor,
  );

  for (let edgeIndex = 0; edgeIndex < run.points.length - 1; edgeIndex += 1) {
    const edgeColor = routeCycleSegmentDisplayColor(
      run.edgeSegmentOrders[edgeIndex],
      firstOrder,
      lastOrder,
      fallbackColor,
    );
    if (edgeIndex > 0 && edgeColor !== currentColor) {
      segments.push({ points: currentPoints, color: currentColor });
      currentPoints = [run.points[edgeIndex]];
      currentColor = edgeColor;
    }
    currentPoints.push(run.points[edgeIndex + 1]);
  }
  segments.push({ points: currentPoints, color: currentColor });

  return segments.map((segment) => ({
    pointText: pointText(segment.points, left, top),
    edgeRepeatCount: run.edgeRepeatCount,
    edgeRepeatIndex: run.edgeRepeatIndex,
    offsetLane: run.offsetLane,
    color: segment.color,
  }));
}

function canJoinContinuousRouteCycleRuns(
  previous: RouteCycleGuideRun,
  current: RouteCycleGuideRun,
): boolean {
  if (!previous.isRawPassRun || !current.isRawPassRun) {
    return false;
  }
  if (
    parseRouteCycleSegmentOrder(previous.lastSegmentOrder) === null ||
    parseRouteCycleSegmentOrder(current.firstSegmentOrder) === null ||
    !areRouteCycleSegmentOrdersConsecutive(
      previous.lastSegmentOrder,
      current.firstSegmentOrder,
    )
  ) {
    return false;
  }
  if (
    normalizeRouteCycleNodeId(previous.lastPassToNode) === null ||
    normalizeRouteCycleNodeId(current.firstPassFromNode) === null ||
    !areRouteCycleNodesEqual(previous.lastPassToNode, current.firstPassFromNode)
  ) {
    return false;
  }
  if (previous.basePoints.length < 2 || current.basePoints.length < 2) {
    return false;
  }

  const previousBaseEnd = previous.basePoints[previous.basePoints.length - 1];
  const currentBaseStart = current.basePoints[0];
  const baseGapPx = Math.hypot(
    previousBaseEnd.x - currentBaseStart.x,
    previousBaseEnd.y - currentBaseStart.y,
  );
  return Number.isFinite(baseGapPx) && baseGapPx <= ROUTE_CYCLE_BASE_JOIN_MAX_GAP_PX;
}

function terminalSegmentVector(points: PixelPoint[]): PixelPoint | null {
  if (points.length < 2) {
    return null;
  }
  const end = points[points.length - 1];
  for (let index = points.length - 2; index >= 0; index -= 1) {
    const start = points[index];
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length >= 1) {
      return { x: (end.x - start.x) / length, y: (end.y - start.y) / length };
    }
  }
  return null;
}

function initialSegmentVector(points: PixelPoint[]): PixelPoint | null {
  if (points.length < 2) {
    return null;
  }
  const start = points[0];
  for (let index = 1; index < points.length; index += 1) {
    const end = points[index];
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length >= 1) {
      return { x: (end.x - start.x) / length, y: (end.y - start.y) / length };
    }
  }
  return null;
}

function buildContinuousRouteCycleOffsetJoins(
  runs: RouteCycleGuideRun[],
): RouteCycleGuideJoin[] {
  const joins: RouteCycleGuideJoin[] = [];
  for (let index = 1; index < runs.length; index += 1) {
    const previous = runs[index - 1];
    const current = runs[index];
    if (!canJoinContinuousRouteCycleRuns(previous, current)) {
      continue;
    }
    if (previous.points.length < 2 || current.points.length < 2) {
      continue;
    }

    const previousEnd = previous.points[previous.points.length - 1];
    const currentStart = current.points[0];
    const offsetGapPx = Math.hypot(previousEnd.x - currentStart.x, previousEnd.y - currentStart.y);
    if (
      !Number.isFinite(offsetGapPx) ||
      offsetGapPx < ROUTE_CYCLE_OFFSET_JOIN_MIN_GAP_PX
    ) {
      continue;
    }

    const previousBaseEnd = previous.basePoints[previous.basePoints.length - 1];
    const currentBaseStart = current.basePoints[0];
    const sharedNodePoint = {
      x: (previousBaseEnd.x + currentBaseStart.x) / 2,
      y: (previousBaseEnd.y + currentBaseStart.y) / 2,
    };
    const joinLengthPx =
      Math.hypot(previousEnd.x - sharedNodePoint.x, previousEnd.y - sharedNodePoint.y) +
      Math.hypot(currentStart.x - sharedNodePoint.x, currentStart.y - sharedNodePoint.y);
    if (!Number.isFinite(joinLengthPx)) {
      continue;
    }

    const previousDirection = terminalSegmentVector(previous.basePoints);
    const currentDirection = initialSegmentVector(current.basePoints);
    const previousDisplayDirection = terminalSegmentVector(previous.points) ?? previousDirection;
    const currentDisplayDirection = initialSegmentVector(current.points) ?? currentDirection;
    const directionDot =
      previousDirection && currentDirection
        ? previousDirection.x * currentDirection.x + previousDirection.y * currentDirection.y
        : 1;
    if (previousDisplayDirection && currentDisplayDirection) {
      const shouldSmoothJoin =
        directionDot <= ROUTE_CYCLE_UTURN_DOT_THRESHOLD ||
        isRouteCycleStraightJoinSharp(
          previousEnd,
          currentStart,
          previousDisplayDirection,
          currentDisplayDirection,
        );
      if (shouldSmoothJoin) {
        const smoothJoin = buildRouteCycleSmoothTurnJoin(
          previousEnd,
          currentStart,
          previousDisplayDirection,
          currentDisplayDirection,
        );
        if (smoothJoin) {
          joins.push(smoothJoin);
          continue;
        }
      }
    }

    joins.push({ points: [previousEnd, currentStart] });
  }
  return joins;
}

function pointText(points: PixelPoint[], left: number, top: number): string {
  return points.map((point) => `${point.x - left},${point.y - top}`).join(" ");
}

function pathPointText(point: PixelPoint, left: number, top: number): string {
  return `${point.x - left},${point.y - top}`;
}

function clampRouteCycleHandleLength(value: number): number {
  return Math.min(
    ROUTE_CYCLE_SMOOTH_JOIN_BEZIER_MAX_HANDLE_PX,
    Math.max(ROUTE_CYCLE_SMOOTH_JOIN_BEZIER_MIN_HANDLE_PX, value),
  );
}

function isRouteCycleStraightJoinSharp(
  start: PixelPoint,
  end: PixelPoint,
  startDirection: PixelPoint,
  endDirection: PixelPoint,
): boolean {
  const chordLength = Math.hypot(end.x - start.x, end.y - start.y);
  if (!Number.isFinite(chordLength) || chordLength < ROUTE_CYCLE_OFFSET_JOIN_MIN_GAP_PX) {
    return false;
  }
  const chordDirection = {
    x: (end.x - start.x) / chordLength,
    y: (end.y - start.y) / chordLength,
  };
  const startDot = chordDirection.x * startDirection.x + chordDirection.y * startDirection.y;
  const endDot = chordDirection.x * endDirection.x + chordDirection.y * endDirection.y;
  return (
    !Number.isFinite(startDot) ||
    !Number.isFinite(endDot) ||
    startDot < ROUTE_CYCLE_SHARP_JOIN_DOT_THRESHOLD ||
    endDot < ROUTE_CYCLE_SHARP_JOIN_DOT_THRESHOLD
  );
}

function buildRouteCycleSmoothTurnJoin(
  start: PixelPoint,
  end: PixelPoint,
  startDirection: PixelPoint,
  endDirection: PixelPoint,
): RouteCycleGuideJoin | null {
  const chordLength = Math.hypot(end.x - start.x, end.y - start.y);
  if (!Number.isFinite(chordLength) || chordLength < ROUTE_CYCLE_OFFSET_JOIN_MIN_GAP_PX) {
    return null;
  }

  const handleLength = clampRouteCycleHandleLength(chordLength * 0.45);
  const firstControl = {
    x: start.x + startDirection.x * handleLength,
    y: start.y + startDirection.y * handleLength,
  };
  const secondControl = {
    x: end.x - endDirection.x * handleLength,
    y: end.y - endDirection.y * handleLength,
  };
  const controlPathLength =
    Math.hypot(firstControl.x - start.x, firstControl.y - start.y) +
    Math.hypot(secondControl.x - firstControl.x, secondControl.y - firstControl.y) +
    Math.hypot(end.x - secondControl.x, end.y - secondControl.y);
  if (!Number.isFinite(controlPathLength)) {
    return null;
  }

  return { points: [start, end], cubicControls: [firstControl, secondControl] };
}

function routeCycleJoinPathText(join: RouteCycleGuideJoin, left: number, top: number): string {
  if (join.points.length < 2) {
    return "";
  }
  const [start, end] = join.points;
  if (join.cubicControls && end) {
    const [firstControl, secondControl] = join.cubicControls;
    return [
      `M ${pathPointText(start, left, top)}`,
      `C ${pathPointText(firstControl, left, top)} ${pathPointText(secondControl, left, top)} ${pathPointText(end, left, top)}`,
    ].join(" ");
  }
  const [, ...rest] = join.points;
  return [
    `M ${pathPointText(start, left, top)}`,
    ...rest.map((point) => `L ${pathPointText(point, left, top)}`),
  ].join(" ");
}

function routeCyclePathLength(points: PixelPoint[]): number {
  let totalLength = 0;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    totalLength += Math.hypot(current.x - previous.x, current.y - previous.y);
  }
  return totalLength;
}

function clampRouteCycleRatio(value: number): number {
  return Math.min(0.97, Math.max(0.08, value));
}

function normalizeRouteCycleNodeId(value: number | string | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  const normalized = String(value).trim();
  return normalized.length ? normalized : null;
}

function parseRouteCycleSegmentOrder(value: number | string | null | undefined): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function areRouteCycleNodesEqual(
  previous: number | string | null | undefined,
  next: number | string | null | undefined,
): boolean {
  const previousNode = normalizeRouteCycleNodeId(previous);
  const nextNode = normalizeRouteCycleNodeId(next);
  return previousNode !== null && nextNode !== null && previousNode === nextNode;
}

function areRouteCycleSegmentOrdersConsecutive(
  previous: number | string | null | undefined,
  next: number | string | null | undefined,
): boolean {
  const previousOrder = parseRouteCycleSegmentOrder(previous);
  const nextOrder = parseRouteCycleSegmentOrder(next);
  return previousOrder !== null && nextOrder !== null && nextOrder === previousOrder + 1;
}

function segmentVector(points: PixelPoint[]): PixelPoint | null {
  if (points.length < 2) {
    return null;
  }
  const start = points[0];
  for (let index = points.length - 1; index >= 1; index -= 1) {
    const end = points[index];
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length >= 1) {
      return { x: (end.x - start.x) / length, y: (end.y - start.y) / length };
    }
  }
  return null;
}

function isClosedRouteCycleSegment(points: PixelPoint[]): boolean {
  if (points.length < 4) {
    return false;
  }
  const start = points[0];
  const end = points[points.length - 1];
  return Math.hypot(end.x - start.x, end.y - start.y) <= 2;
}

function canAppendRouteCycleRun(
  run: RouteCycleGuideRun,
  segment: RouteCyclePixelSegment,
  preferChainContinuity: boolean,
): boolean {
  if (run.points.length < 2 || segment.points.length < 2) {
    return false;
  }
  if (run.isClosedLoop || segment.isClosedLoop) {
    return false;
  }

  const hasComparableOrders =
    parseRouteCycleSegmentOrder(run.lastSegmentOrder) !== null &&
    parseRouteCycleSegmentOrder(segment.segmentOrder) !== null;
  if (
    hasComparableOrders &&
    !areRouteCycleSegmentOrdersConsecutive(run.lastSegmentOrder, segment.segmentOrder)
  ) {
    return false;
  }

  const hasComparableNodes =
    normalizeRouteCycleNodeId(run.lastPassToNode) !== null &&
    normalizeRouteCycleNodeId(segment.passFromNode) !== null;
  if (
    hasComparableNodes &&
    !areRouteCycleNodesEqual(run.lastPassToNode, segment.passFromNode)
  ) {
    return false;
  }

  if (segment.isRawPassSegment && (!hasComparableOrders || !hasComparableNodes)) {
    return false;
  }

  if (!preferChainContinuity) {
    if (
      run.edgeRepeatCount !== segment.edgeRepeatCount ||
      run.edgeRepeatIndex !== segment.edgeRepeatIndex ||
      run.offsetLane !== segment.offsetLane
    ) {
      return false;
    }
  }

  const runPoints = preferChainContinuity ? run.basePoints : run.points;
  const segmentPoints = preferChainContinuity ? segment.basePoints : segment.points;
  const runEnd = runPoints[runPoints.length - 1];
  const segmentStart = segmentPoints[0];
  const endpointDistance = Math.hypot(runEnd.x - segmentStart.x, runEnd.y - segmentStart.y);
  if (endpointDistance > 8) {
    return false;
  }

  const runVector = terminalSegmentVector(runPoints);
  const segmentDirection = segmentVector(segmentPoints);
  if (!runVector || !segmentDirection) {
    return false;
  }

  const directionDot = runVector.x * segmentDirection.x + runVector.y * segmentDirection.y;
  return directionDot >= -0.35;
}

function buildRouteCycleGuideRuns(
  segments: RouteCyclePixelSegment[],
  preferChainContinuity: boolean,
): RouteCycleGuideRun[] {
  const runs: RouteCycleGuideRun[] = [];
  segments.forEach((segment, index) => {
    const currentRun = runs[runs.length - 1];
    if (currentRun && canAppendRouteCycleRun(currentRun, segment, preferChainContinuity)) {
      currentRun.points = currentRun.points.concat(segment.points.slice(1));
      currentRun.basePoints = currentRun.basePoints.concat(segment.basePoints.slice(1));
      currentRun.edgeOffsetsPx = currentRun.edgeOffsetsPx.concat(segment.edgeOffsetsPx);
      currentRun.edgeSegmentOrders = currentRun.edgeSegmentOrders.concat(segment.edgeSegmentOrders);
      currentRun.lastSegmentOrder = segment.segmentOrder;
      currentRun.lastPassToNode = segment.passToNode;
      return;
    }

    runs.push({
      points: segment.points,
      basePoints: segment.basePoints,
      edgeOffsetsPx: segment.edgeOffsetsPx,
      edgeSegmentOrders: segment.edgeSegmentOrders,
      isRawPassRun: segment.isRawPassSegment,
      segmentOrder: segment.segmentOrder,
      firstSegmentOrder: segment.segmentOrder,
      lastSegmentOrder: segment.segmentOrder,
      firstPassFromNode: segment.passFromNode,
      lastPassToNode: segment.passToNode,
      segmentIndex: index,
      edgeRepeatCount: segment.edgeRepeatCount,
      edgeRepeatIndex: segment.edgeRepeatIndex,
      offsetLane: segment.offsetLane,
      isClosedLoop: segment.isClosedLoop,
    });
  });
  return runs;
}

function buildRouteCycleGuideArrow(
  points: PixelPoint[],
  positionRatio: number,
  style: RouteCycleGuideStyle,
): RouteCycleGuideArrow | null {
  if (points.length < 2) {
    return null;
  }

  const lengths: number[] = [];
  let totalLength = 0;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const length = Math.hypot(current.x - previous.x, current.y - previous.y);
    lengths.push(length);
    totalLength += length;
  }

  if (totalLength < 32) {
    return null;
  }

  const targetLength = totalLength * positionRatio;
  let walkedLength = 0;
  for (let index = 1; index < points.length; index += 1) {
    const segmentLength = lengths[index - 1];
    if (segmentLength < 1) {
      continue;
    }

    if (walkedLength + segmentLength >= targetLength) {
      const previous = points[index - 1];
      const current = points[index];
      const ratio = (targetLength - walkedLength) / segmentLength;
      return {
        x: previous.x + (current.x - previous.x) * ratio,
        y: previous.y + (current.y - previous.y) * ratio,
        angle: Math.atan2(current.y - previous.y, current.x - previous.x) * (180 / Math.PI),
        points: buildRouteCycleHalfArrowheadPoints(previous, current, ratio, style),
      };
    }

    walkedLength += segmentLength;
  }

  return null;
}

function buildRouteCycleGuideArrowsByCumulativeDistance(
  runs: RouteCycleGuideRun[],
  style: RouteCycleGuideStyle,
): RouteCycleGuideArrow[] {
  const arrows: RouteCycleGuideArrow[] = [];
  let accumulatedLengthPx = 0;
  let previousRunEnd: PixelPoint | null = null;

  runs.forEach((run) => {
    if (run.points.length < 2) {
      return;
    }

    const runStart = run.points[0];
    if (previousRunEnd) {
      const gapPx = Math.hypot(previousRunEnd.x - runStart.x, previousRunEnd.y - runStart.y);
      if (gapPx > ROUTE_CYCLE_ARROW_RUN_CONTINUITY_GAP_PX) {
        accumulatedLengthPx = 0;
      }
    }

    const runEnd = run.points[run.points.length - 1];
    previousRunEnd = runEnd;

    const runLengthPx = routeCyclePathLength(run.points);
    if (runLengthPx < 1) {
      return;
    }

    let targetDistanceInRunPx = ROUTE_CYCLE_ARROW_CUMULATIVE_INTERVAL_PX - accumulatedLengthPx;
    if (targetDistanceInRunPx > runLengthPx) {
      accumulatedLengthPx += runLengthPx;
      return;
    }

    let lastArrowDistanceInRunPx = 0;
    while (targetDistanceInRunPx <= runLengthPx) {
      const arrow = buildRouteCycleGuideArrow(
        run.points,
        clampRouteCycleRatio(targetDistanceInRunPx / runLengthPx),
        style,
      );
      if (arrow) {
        arrows.push(arrow);
      }
      lastArrowDistanceInRunPx = targetDistanceInRunPx;
      targetDistanceInRunPx += ROUTE_CYCLE_ARROW_CUMULATIVE_INTERVAL_PX;
    }

    accumulatedLengthPx = runLengthPx - lastArrowDistanceInRunPx;
  });

  return arrows;
}

function buildRouteCycleHalfArrowheadPoints(
  previous: PixelPoint,
  current: PixelPoint,
  ratio: number,
  style: RouteCycleGuideStyle,
): PixelPoint[] {
  const arrowHeadLength = style.marker.lengthPx;
  const arrowHeadWidth = style.marker.widthPx;
  const x = previous.x + (current.x - previous.x) * ratio;
  const y = previous.y + (current.y - previous.y) * ratio;
  const dx = current.x - previous.x;
  const dy = current.y - previous.y;
  const length = Math.hypot(dx, dy);
  if (length < 1) {
    return [];
  }

  const unitX = dx / length;
  const unitY = dy / length;
  const guideNormalX = unitY;
  const guideNormalY = -unitX;
  const baseX = x - unitX * arrowHeadLength;
  const baseY = y - unitY * arrowHeadLength;
  return [
    { x, y },
    { x: baseX, y: baseY },
    {
      x: baseX + guideNormalX * arrowHeadWidth,
      y: baseY + guideNormalY * arrowHeadWidth,
    },
  ];
}

function polygonPointText(points: PixelPoint[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

type PendingInstructionOverrides = Record<string, InstructionState>;
type NoInstructionCycleHints = Record<string, "after_black_clear">;

type FeatureDistanceMatch = {
  feature: RoadFeature;
  distancePx: number;
};

type LegendItem = {
  label: string;
  color: string;
  width: number;
  lineStyle?: string;
};

type RouteResolution = {
  match: FeatureDistanceMatch | null;
  method: string;
  detail: string;
};

type LineStyleKey =
  | "target"
  | "connector"
  | "return"
  | "candidate"
  | "nonOperable"
  | "strongProhibit"
  | "targetRequest"
  | "conditionalAllow"
  | "unmetTarget"
  | "partialUnmetTarget";

type LineStyle = {
  lineColor: string;
  lineWidth: number;
  lineDasharray?: number[];
};

type LineStylesConfig = Partial<Record<LineStyleKey, Partial<LineStyle>>>;

const EMPTY_FEATURE_COLLECTION: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

const LINE_STYLE_KEYS: LineStyleKey[] = [
  "target",
  "connector",
  "return",
  "candidate",
  "nonOperable",
  "strongProhibit",
  "targetRequest",
  "conditionalAllow",
  "unmetTarget",
  "partialUnmetTarget",
];

const DEFAULT_LINE_STYLES: Record<LineStyleKey, LineStyle> = {
  target: { lineColor: "rgba(0, 0, 255, 1)", lineWidth: 6 },
  connector: { lineColor: "rgba(0, 255, 255, 1)", lineWidth: 6 },
  return: { lineColor: "rgba(0, 191, 255, 1)", lineWidth: 6 },
  candidate: { lineColor: "rgba(105, 105, 105, 0.98)", lineWidth: 2 },
  nonOperable: { lineColor: "rgba(220, 220, 220, 0.98)", lineWidth: 2 },
  strongProhibit: { lineColor: "rgba(17, 24, 39, 0.98)", lineWidth: 6 },
  targetRequest: { lineColor: "rgba(217, 70, 239, 0.98)", lineWidth: 6 },
  conditionalAllow: { lineColor: "rgba(255, 165, 0, 0.98)", lineWidth: 6 },
  unmetTarget: { lineColor: "rgba(220, 38, 38, 0.98)", lineWidth: 6 },
  partialUnmetTarget: {
    lineColor: "rgba(220, 38, 38, 0.98)",
    lineWidth: 6,
    lineDasharray: [0.35, 1.4],
  },
};

function normalizeLineDasharray(value: unknown, fallback: number[] | undefined): number[] | undefined {
  if (!Array.isArray(value)) {
    return fallback;
  }

  const normalized = value
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item) && item >= 0);

  return normalized.length > 0 ? normalized : fallback;
}

function normalizeLineStyle(value: unknown, fallback: LineStyle): LineStyle {
  if (typeof value !== "object" || value === null) {
    return fallback;
  }

  const raw = value as Record<string, unknown>;
  const lineColor =
    typeof raw.lineColor === "string" && raw.lineColor.trim() !== ""
      ? raw.lineColor
      : fallback.lineColor;
  const lineWidth = Number(raw.lineWidth);

  return {
    lineColor,
    lineWidth: Number.isFinite(lineWidth) && lineWidth > 0 ? lineWidth : fallback.lineWidth,
    lineDasharray: normalizeLineDasharray(raw.lineDasharray, fallback.lineDasharray),
  };
}

function normalizePositiveNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeNonNegativeNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function mergeLineStyles(value: unknown): Record<LineStyleKey, LineStyle> {
  const lineStyles =
    typeof value === "object" && value !== null
      ? ((value as Record<string, unknown>).lineStyles ?? value)
      : null;
  const rawStyles =
    typeof lineStyles === "object" && lineStyles !== null ? (lineStyles as LineStylesConfig) : {};

  return LINE_STYLE_KEYS.reduce((merged, key) => {
    merged[key] = normalizeLineStyle(rawStyles[key], DEFAULT_LINE_STYLES[key]);
    return merged;
  }, {} as Record<LineStyleKey, LineStyle>);
}

function normalizeRouteCycleGuideStyle(value: unknown): RouteCycleGuideStyle {
  const rawRoot = typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
  const rawGuideStyles =
    typeof rawRoot.guideStyles === "object" && rawRoot.guideStyles !== null
      ? (rawRoot.guideStyles as Record<string, unknown>)
      : {};
  const rawRouteCycleGuide =
    typeof rawGuideStyles.routeCycleGuide === "object" && rawGuideStyles.routeCycleGuide !== null
      ? (rawGuideStyles.routeCycleGuide as Record<string, unknown>)
      : {};
  const rawMarker =
    typeof rawRouteCycleGuide.marker === "object" && rawRouteCycleGuide.marker !== null
      ? (rawRouteCycleGuide.marker as Record<string, unknown>)
      : {};
  const rawMarkerLayout =
    typeof rawRouteCycleGuide.markerLayout === "object" &&
    rawRouteCycleGuide.markerLayout !== null
      ? (rawRouteCycleGuide.markerLayout as Record<string, unknown>)
      : {};

  const lineColor =
    typeof rawRouteCycleGuide.lineColor === "string" && rawRouteCycleGuide.lineColor.trim() !== ""
      ? rawRouteCycleGuide.lineColor
      : DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.lineColor;
  const markerType = rawMarker.type === "arrow" ? "arrow" : DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.marker.type;
  const markerFillColor =
    typeof rawMarker.fillColor === "string" && rawMarker.fillColor.trim() !== ""
      ? rawMarker.fillColor
      : DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.marker.fillColor;
  const markerStrokeColor =
    typeof rawMarker.strokeColor === "string" && rawMarker.strokeColor.trim() !== ""
      ? rawMarker.strokeColor
      : DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.marker.strokeColor;

  return {
    lineColor,
    lineWidth: normalizePositiveNumber(
      rawRouteCycleGuide.lineWidth,
      DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.lineWidth,
    ),
    baseOffsetPx: normalizeNonNegativeNumber(
      rawRouteCycleGuide.baseOffsetPx,
      DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.baseOffsetPx,
    ),
    laneOffsetPx: normalizeNonNegativeNumber(
      rawRouteCycleGuide.laneOffsetPx,
      DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.laneOffsetPx,
    ),
    marker: {
      type: markerType,
      fillColor: markerFillColor,
      strokeColor: markerStrokeColor,
      lengthPx: normalizePositiveNumber(
        rawMarker.lengthPx,
        DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.marker.lengthPx,
      ),
      widthPx: normalizePositiveNumber(
        rawMarker.widthPx,
        DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.marker.widthPx,
      ),
    },
    markerLayout: {
      startPaddingPx: normalizeNonNegativeNumber(
        rawMarkerLayout.startPaddingPx,
        DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.markerLayout.startPaddingPx,
      ),
      endPaddingPx: normalizeNonNegativeNumber(
        rawMarkerLayout.endPaddingPx,
        DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.markerLayout.endPaddingPx,
      ),
      minRunLengthPx: normalizePositiveNumber(
        rawMarkerLayout.minRunLengthPx,
        DEFAULT_ROUTE_CYCLE_GUIDE_STYLE.markerLayout.minRunLengthPx,
      ),
    },
  };
}

function buildLinePaint(style: LineStyle): LayerProps["paint"] {
  const paint: LayerProps["paint"] = {
    "line-color": style.lineColor,
    "line-width": style.lineWidth,
  };

  if (style.lineDasharray && style.lineDasharray.length > 0) {
    paint["line-dasharray"] = style.lineDasharray;
  }

  return paint;
}

const MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "component-background",
      type: "background",
      paint: {
        "background-color": "#f8fafc",
      },
    },
  ],
};

const BASEMAP_SOURCE_ID = "osm-basemap-source";
const BASEMAP_LAYER_ID = "osm-basemap-layer";
const ROAD_SOURCE_ID = "road-source";
const ROAD_STATE_SOURCE_ID = "road-state-source";
const WHEEL_ZOOM_RATE = 1 / 900;
const TRACKPAD_ZOOM_RATE = 1 / 150;
const BACKGROUND_ROAD_LAYER_ID = "background-road-layer";
const OPERABLE_ROAD_CASING_LAYER_ID = "operable-road-casing-layer";
const OPERABLE_ROAD_BASE_LAYER_ID = "operable-road-base-layer";
const ROUTE_CASING_LAYER_ID = "route-casing-layer";
const ROUTE_LAYER_ID = "route-layer";
const CONDITIONAL_ROAD_CASING_LAYER_ID = "conditional-road-casing-layer";
const EXCLUDED_ROAD_CASING_LAYER_ID = "excluded-road-casing-layer";
const INCLUDED_ROAD_CASING_LAYER_ID = "included-road-casing-layer";
const FAILED_INCLUDED_ROAD_CASING_LAYER_ID = "failed-included-road-casing-layer";
const FAILED_PARTIAL_ROAD_CASING_LAYER_ID = "failed-partial-road-casing-layer";
const CONDITIONAL_ROAD_TOP_LAYER_ID = "conditional-road-top-layer";
const EXCLUDED_ROAD_TOP_LAYER_ID = "excluded-road-top-layer";
const INCLUDED_ROAD_TOP_LAYER_ID = "included-road-top-layer";
const FAILED_INCLUDED_ROAD_TOP_LAYER_ID = "failed-included-road-top-layer";
const FAILED_PARTIAL_ROAD_TOP_LAYER_ID = "failed-partial-road-top-layer";
const FOREGROUND_CASING_COLOR = "rgba(255, 255, 255, 0.94)";
const SUBTLE_CASING_COLOR = "rgba(255, 255, 255, 0.78)";

function buildBackgroundRoadLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: BACKGROUND_ROAD_LAYER_ID,
    type: "line",
    source: ROAD_SOURCE_ID,
    filter: ["==", ["get", "display_kind"], "background"],
    paint: buildLinePaint(lineStyles.nonOperable),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildLineCasingPaint(
  style: LineStyle,
  extraWidth = 5,
  color = FOREGROUND_CASING_COLOR,
): LayerProps["paint"] {
  const paint: LayerProps["paint"] = {
    "line-color": color,
    "line-width": style.lineWidth + extraWidth,
    "line-opacity": 1,
  };

  if (style.lineDasharray && style.lineDasharray.length > 0) {
    paint["line-dasharray"] = style.lineDasharray;
  }

  return paint;
}

function normalizeShowBasemap(value: unknown): boolean {
  if (typeof value !== "object" || value === null) {
    return true;
  }

  const raw = value as Record<string, unknown>;
  const rawMapDisplay =
    typeof raw.mapDisplay === "object" && raw.mapDisplay !== null
      ? (raw.mapDisplay as Record<string, unknown>)
      : {};
  const showBasemap = raw.showBasemap ?? rawMapDisplay.showBasemap;
  return typeof showBasemap === "boolean" ? showBasemap : true;
}

function buildOperableRoadCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: OPERABLE_ROAD_CASING_LAYER_ID,
    type: "line",
    source: ROAD_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      [
        "any",
        ["==", ["get", "diff_display_state"], "transparent"],
        ["!", ["has", "diff_display_state"]],
      ],
      ["!=", ["get", "is_base_suppressed_by_final_state"], true],
    ],
    paint: {
      "line-color": SUBTLE_CASING_COLOR,
      "line-width": [
        "match",
        ["get", "base_display_state"],
        "target",
        lineStyles.target.lineWidth + 5,
        "connector",
        lineStyles.connector.lineWidth + 5,
        "return",
        lineStyles.return.lineWidth + 5,
        "candidate",
        lineStyles.candidate.lineWidth + 3,
        lineStyles.candidate.lineWidth + 3,
      ],
      "line-opacity": 1,
    },
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildOperableRoadBaseLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: OPERABLE_ROAD_BASE_LAYER_ID,
    type: "line",
    source: ROAD_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      [
        "any",
        ["==", ["get", "diff_display_state"], "transparent"],
        ["!", ["has", "diff_display_state"]],
      ],
      ["!=", ["get", "is_base_suppressed_by_final_state"], true],
    ],
    paint: {
      "line-color": [
        "match",
        ["get", "base_display_state"],
        "target",
        lineStyles.target.lineColor,
        "connector",
        lineStyles.connector.lineColor,
        "return",
        lineStyles.return.lineColor,
        "candidate",
        lineStyles.candidate.lineColor,
        lineStyles.candidate.lineColor,
      ],
      "line-width": [
        "match",
        ["get", "base_display_state"],
        "target",
        lineStyles.target.lineWidth,
        "connector",
        lineStyles.connector.lineWidth,
        "return",
        lineStyles.return.lineWidth,
        "candidate",
        lineStyles.candidate.lineWidth,
        lineStyles.candidate.lineWidth,
      ],
    },
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildRouteCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: ROUTE_CASING_LAYER_ID,
    type: "line",
    source: "route-source",
    filter: [
      "all",
      ["==", ["get", "display_kind"], "route"],
      ["!=", ["get", "is_route_suppressed_by_final_state"], true],
    ],
    paint: {
      "line-color": FOREGROUND_CASING_COLOR,
      "line-width": [
        "match",
        ["get", "display_state"],
        "target",
        lineStyles.target.lineWidth + 6,
        "connector",
        lineStyles.connector.lineWidth + 6,
        "return",
        lineStyles.return.lineWidth + 6,
        lineStyles.target.lineWidth + 6,
      ],
      "line-opacity": 1,
    },
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildRouteLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: ROUTE_LAYER_ID,
    type: "line",
    source: "route-source",
    filter: [
      "all",
      ["==", ["get", "display_kind"], "route"],
      ["!=", ["get", "is_route_suppressed_by_final_state"], true],
    ],
    paint: {
      "line-color": [
        "match",
        ["get", "display_state"],
        "target",
        lineStyles.target.lineColor,
        "connector",
        lineStyles.connector.lineColor,
        "return",
        lineStyles.return.lineColor,
        lineStyles.target.lineColor,
      ],
      "line-width": [
        "match",
        ["get", "display_state"],
        "target",
        lineStyles.target.lineWidth,
        "connector",
        lineStyles.connector.lineWidth,
        "return",
        lineStyles.return.lineWidth,
        lineStyles.target.lineWidth,
      ],
    },
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildConditionalRoadCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: CONDITIONAL_ROAD_CASING_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "orange"],
    ],
    paint: buildLineCasingPaint(lineStyles.conditionalAllow),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildConditionalRoadTopLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: CONDITIONAL_ROAD_TOP_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "orange"],
    ],
    paint: buildLinePaint(lineStyles.conditionalAllow),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildExcludedRoadCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: EXCLUDED_ROAD_CASING_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "black"],
    ],
    paint: buildLineCasingPaint(lineStyles.strongProhibit),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildExcludedRoadTopLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: EXCLUDED_ROAD_TOP_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "black"],
    ],
    paint: buildLinePaint(lineStyles.strongProhibit),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildIncludedRoadCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: INCLUDED_ROAD_CASING_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "magenta"],
    ],
    paint: buildLineCasingPaint(lineStyles.targetRequest),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildIncludedRoadTopLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: INCLUDED_ROAD_TOP_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "magenta"],
    ],
    paint: buildLinePaint(lineStyles.targetRequest),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildFailedIncludedRoadCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: FAILED_INCLUDED_ROAD_CASING_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "red"],
      ["!=", ["get", "is_failed_partial"], true],
    ],
    paint: buildLineCasingPaint(lineStyles.unmetTarget),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildFailedIncludedRoadTopLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: FAILED_INCLUDED_ROAD_TOP_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "red"],
      ["!=", ["get", "is_failed_partial"], true],
    ],
    paint: buildLinePaint(lineStyles.unmetTarget),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildFailedPartialRoadCasingLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: FAILED_PARTIAL_ROAD_CASING_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "red"],
      ["==", ["get", "is_failed_partial"], true],
    ],
    paint: buildLineCasingPaint(lineStyles.partialUnmetTarget),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

function buildFailedPartialRoadTopLayer(lineStyles: Record<LineStyleKey, LineStyle>): LayerProps {
  return {
    id: FAILED_PARTIAL_ROAD_TOP_LAYER_ID,
    type: "line",
    source: ROAD_STATE_SOURCE_ID,
    filter: [
      "all",
      ["==", ["get", "display_kind"], "operable"],
      ["==", ["get", "display_state"], "red"],
      ["==", ["get", "is_failed_partial"], true],
    ],
    paint: buildLinePaint(lineStyles.partialUnmetTarget),
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
  };
}

const ROAD_PICK_THRESHOLD_PX = 10;
const ROUTE_PICK_THRESHOLD_PX = 18;
const ROUTE_FALLBACK_THRESHOLD_PX = 28;
const INSTRUCTION_OVERLAY_QUERY_TOLERANCE_PX = 4;
const CLICKED_VISIBLE_ROAD_QUERY_TOLERANCE_PX = ROUTE_PICK_THRESHOLD_PX;
const INSTRUCTION_OVERLAY_LAYER_IDS = [
  EXCLUDED_ROAD_TOP_LAYER_ID,
  CONDITIONAL_ROAD_TOP_LAYER_ID,
  INCLUDED_ROAD_TOP_LAYER_ID,
  FAILED_INCLUDED_ROAD_TOP_LAYER_ID,
  FAILED_PARTIAL_ROAD_TOP_LAYER_ID,
].filter((layerId): layerId is string => typeof layerId === "string" && layerId.trim() !== "");
const CLICKED_VISIBLE_ROAD_LAYER_IDS = [
  EXCLUDED_ROAD_TOP_LAYER_ID,
  CONDITIONAL_ROAD_TOP_LAYER_ID,
  INCLUDED_ROAD_TOP_LAYER_ID,
  FAILED_INCLUDED_ROAD_TOP_LAYER_ID,
  FAILED_PARTIAL_ROAD_TOP_LAYER_ID,
  ROUTE_LAYER_ID,
  OPERABLE_ROAD_BASE_LAYER_ID,
  BACKGROUND_ROAD_LAYER_ID,
].filter((layerId): layerId is string => typeof layerId === "string" && layerId.trim() !== "");

function normalizeEdgeIdValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }

  const text = String(value).trim();
  if (text === "" || text.toLowerCase() === "nan") {
    return "";
  }

  const integerLikeMatch = text.match(/^(-?\d+)(?:\.0+)?$/);
  if (integerLikeMatch) {
    return integerLikeMatch[1];
  }

  return text;
}

function edgeIdToKey(edgeId: EdgeId): string {
  return `${edgeId.u}__${edgeId.v}__${edgeId.key}`;
}

function reverseEdgeId(edgeId: EdgeId): EdgeId {
  return {
    u: edgeId.v,
    v: edgeId.u,
    key: edgeId.key,
  };
}

function findRoadOptionByEdgeId(
  roadOptionByKey: Map<string, RoadOption>,
  edgeId: EdgeId,
): { option: RoadOption | null; edgeId: EdgeId; edgeKey: string; reversed: boolean } {
  const edgeKey = edgeIdToKey(edgeId);
  const directOption = roadOptionByKey.get(edgeKey);
  if (directOption) {
    return { option: directOption, edgeId, edgeKey, reversed: false };
  }

  const reversedEdgeId = reverseEdgeId(edgeId);
  const reversedEdgeKey = edgeIdToKey(reversedEdgeId);
  return {
    option: roadOptionByKey.get(reversedEdgeKey) ?? null,
    edgeId: reversedEdgeId,
    edgeKey: reversedEdgeKey,
    reversed: true,
  };
}

function edgeIdFromProperties(props: RoadFeatureProperties): EdgeId {
  return {
    u: normalizeEdgeIdValue(props.u),
    v: normalizeEdgeIdValue(props.v),
    key: normalizeEdgeIdValue(props.key),
  };
}

function buildMapViewState(viewState: ViewStateInput): MapViewState {
  return {
    latitude: Number.isFinite(viewState.lat) ? viewState.lat : 43.426,
    longitude: Number.isFinite(viewState.lon) ? viewState.lon : 141.886,
    zoom: Number.isFinite(viewState.zoom) ? viewState.zoom : 12,
    bearing: 0,
    pitch: 0,
  };
}

function isLineGeometry(
  geometry: GeoJSON.Geometry | null | undefined,
): geometry is LineGeometry {
  return geometry?.type === "LineString" || geometry?.type === "MultiLineString";
}

function isRoadFeature(feature: GeoJSON.Feature): feature is RoadFeature {
  return isLineGeometry(feature.geometry);
}

function readRoadProperties(feature: GeoJSON.Feature): RoadFeatureProperties {
  if (!feature.properties || typeof feature.properties !== "object") {
    return {};
  }
  return feature.properties as RoadFeatureProperties;
}

function buildRoadLabel(props: RoadFeatureProperties, edgeId: EdgeId): string {
  const roadIdText =
    typeof props.road_id_text === "string" && props.road_id_text.trim() !== ""
      ? props.road_id_text
      : `u=${edgeId.u}, v=${edgeId.v}, key=${edgeId.key}`;

  const nameText = typeof props.name === "string" && props.name.trim() !== "" ? props.name : "";
  return nameText ? `${nameText} / ${roadIdText}` : roadIdText;
}

function readInstructionState(value: unknown): InstructionState {
  if (
    value === "exclude" ||
    value === "conditional" ||
    value === "include" ||
    value === "include_failed"
  ) {
    return value;
  }
  return "none";
}

function readNoInstructionCycleHint(value: unknown): "after_black_clear" | undefined {
  return value === "after_black_clear" ? "after_black_clear" : undefined;
}

function readDisplayState(value: unknown): DisplayState | null {
  if (
    value === "target" ||
    value === "connector" ||
    value === "return" ||
    value === "candidate" ||
    value === "non_operable" ||
    value === "transparent" ||
    value === "blue" ||
    value === "gray" ||
    value === "black" ||
    value === "orange" ||
    value === "magenta" ||
    value === "red" ||
    value === "none"
  ) {
    return value;
  }
  return null;
}

function readDisplayKind(value: unknown): string {
  if (typeof value !== "string") {
    return "none";
  }
  const text = value.trim();
  return text === "" ? "none" : text;
}

function readBoolean(value: unknown): boolean {
  return value === true;
}

function readBaseDisplayState(value: unknown): BaseDisplayState | null {
  if (
    value === "target" ||
    value === "connector" ||
    value === "return" ||
    value === "candidate" ||
    value === "non_operable"
  ) {
    return value;
  }
  if (value === "blue") {
    return "target";
  }
  if (value === "gray") {
    return "candidate";
  }
  return null;
}

function readDiffDisplayState(value: unknown): DiffDisplayState | null {
  if (
    value === "transparent" ||
    value === "black" ||
    value === "orange" ||
    value === "magenta" ||
    value === "red"
  ) {
    return value;
  }
  return null;
}

function deriveRouteBaseDisplayState(segmentType: unknown): BaseDisplayState {
  const normalized = normalizeRouteSegmentType(segmentType);
  if (normalized === "connector") {
    return "connector";
  }
  if (normalized === "return") {
    return "return";
  }
  return "target";
}

function deriveRoadBaseDisplayState(
  props: RoadFeatureProperties,
  isOnCurrentRoute: boolean,
): BaseDisplayState {
  return (
    readBaseDisplayState(props.base_display_state) ??
    readBaseDisplayState(props.display_state) ??
    (readDisplayKind(props.display_kind) === "background"
      ? "non_operable"
      : isOnCurrentRoute
        ? "target"
        : "candidate")
  );
}

function deriveDiffDisplayState(instructionState: InstructionState): DiffDisplayState {
  if (instructionState === "exclude") {
    return "black";
  }
  if (instructionState === "conditional") {
    return "orange";
  }
  if (instructionState === "include_failed") {
    return "red";
  }
  if (instructionState === "include") {
    return "magenta";
  }
  return "transparent";
}

function deriveVisibleDisplayState(
  baseDisplayState: BaseDisplayState,
  instructionState: InstructionState,
): DisplayState {
  const diffDisplayState = deriveDiffDisplayState(instructionState);
  return diffDisplayState === "transparent" ? baseDisplayState : diffDisplayState;
}

function isInstructionOverlayState(displayState: DisplayState): boolean {
  return (
    displayState === "black" ||
    displayState === "orange" ||
    displayState === "magenta" ||
    displayState === "red"
  );
}

function getFeatureDisplayState(feature: RoadFeature): DisplayState {
  const props = readRoadProperties(feature);
  const displayKind = readDisplayKind(props.display_kind);
  const instructionState = readInstructionState(props.instruction_state);
  const explicitDiffDisplayState = readDiffDisplayState(props.diff_display_state);
  const diffDisplayState =
    explicitDiffDisplayState ?? deriveDiffDisplayState(instructionState);
  if (diffDisplayState !== "transparent") {
    return diffDisplayState;
  }

  if (displayKind === "route") {
    return (
      readBaseDisplayState(props.base_display_state) ??
      readBaseDisplayState(props.display_state) ??
      deriveRouteBaseDisplayState(props.segment_type)
    );
  }

  return deriveRoadBaseDisplayState(props, readBoolean(props.is_on_current_route));
}

function getOptionDisplayState(option: RoadOption | null): DisplayState {
  if (!option) {
    return "none";
  }
  return option.displayState;
}

function getNextInstructionState(
  displayState: DisplayState,
  options?: { shiftKey?: boolean; noInstructionCycleHint?: "after_black_clear" },
): InstructionState {
  const shiftKey = options?.shiftKey === true;
  if (shiftKey) {
    return "none";
  }
  if (displayState === "black") {
    return "none";
  }
  if (displayState === "red") {
    return "include";
  }
  if (displayState === "magenta") {
    return "conditional";
  }
  if (displayState === "orange") {
    return "exclude";
  }
  if (options?.noInstructionCycleHint === "after_black_clear") {
    return "include";
  }
  return "exclude";
}

function buildRoadOptions(
  roadsGeojson: GeoJSON.FeatureCollection | null | undefined,
): RoadOption[] {
  if (!roadsGeojson || !Array.isArray(roadsGeojson.features)) {
    return [];
  }

  const options: RoadOption[] = [];

  for (const feature of roadsGeojson.features) {
    if (!feature || typeof feature !== "object" || !isRoadFeature(feature)) {
      continue;
    }

    const props = readRoadProperties(feature);
    if (props.display_kind !== "operable") {
      continue;
    }

    const edgeId = edgeIdFromProperties(props);
    const instructionState = readInstructionState(props.instruction_state);
    const isOnCurrentRoute = readBoolean(props.is_on_current_route);
    const baseDisplayState = deriveRoadBaseDisplayState(props, isOnCurrentRoute);
    const diffDisplayState =
      readDiffDisplayState(props.diff_display_state) ?? deriveDiffDisplayState(instructionState);
    options.push({
      label: buildRoadLabel(props, edgeId),
      edgeId,
      instructionState,
      noInstructionCycleHint: readNoInstructionCycleHint(props.no_instruction_cycle_hint),
      baseDisplayState,
      diffDisplayState,
      displayState: deriveVisibleDisplayState(baseDisplayState, instructionState),
      isExcluded: instructionState === "exclude",
      isOnCurrentRoute,
      isSelected: Boolean(props.is_selected),
    });
  }

  options.sort((a, b) => a.label.localeCompare(b.label, "ja"));
  return options;
}

function edgeIdKeyFromState(edgeId: EdgeId | null | undefined): string {
  if (!edgeId) {
    return "";
  }
  return edgeIdToKey({
    u: normalizeEdgeIdValue(edgeId.u),
    v: normalizeEdgeIdValue(edgeId.v),
    key: normalizeEdgeIdValue(edgeId.key),
  });
}

function addEdgeIdKeys(target: Set<string>, edgeIds: EdgeId[] | null | undefined): void {
  if (!Array.isArray(edgeIds)) {
    return;
  }
  for (const edgeId of edgeIds) {
    const edgeKey = edgeIdKeyFromState(edgeId);
    if (edgeKey !== "____") {
      target.add(edgeKey);
    }
  }
}

function buildRoadStateLookup(roadState: RoadState | null | undefined): RoadStateLookup {
  const instructionByKey = new Map<string, InstructionState>();
  const failedPartialKeys = new Set<string>();
  const afterBlackClearKeys = new Set<string>();
  const suppressedBaseKeys = new Set<string>();

  if (roadState && Array.isArray(roadState.instructions)) {
    for (const instruction of roadState.instructions) {
      const edgeKey = edgeIdKeyFromState(instruction.edge_id);
      if (edgeKey === "____") {
        continue;
      }
      instructionByKey.set(edgeKey, readInstructionState(instruction.instruction_state));
    }
  }

  addEdgeIdKeys(failedPartialKeys, roadState?.failed_partial_edge_ids);
  addEdgeIdKeys(afterBlackClearKeys, roadState?.after_black_clear_edge_ids);
  addEdgeIdKeys(suppressedBaseKeys, roadState?.suppressed_base_edge_ids);

  return {
    instructionByKey,
    failedPartialKeys,
    afterBlackClearKeys,
    suppressedBaseKeys,
    selectedRoadKey: edgeIdKeyFromState(roadState?.selected_edge_id),
  };
}

function buildEffectiveRoadOptions(
  roadOptions: RoadOption[],
  roadStateLookup: RoadStateLookup,
  pendingInstructionOverrides: PendingInstructionOverrides,
): RoadOption[] {
  return roadOptions.map((option) => {
    const roadKey = edgeIdToKey(option.edgeId);
    const override =
      pendingInstructionOverrides[roadKey] ?? roadStateLookup.instructionByKey.get(roadKey);
    const instructionState = override === undefined ? option.instructionState : override;

    return {
      ...option,
      instructionState,
      diffDisplayState: deriveDiffDisplayState(instructionState),
      displayState: deriveVisibleDisplayState(option.baseDisplayState, instructionState),
      isExcluded: instructionState === "exclude",
      isSelected:
        roadStateLookup.selectedRoadKey !== ""
          ? roadKey === roadStateLookup.selectedRoadKey
          : option.isSelected,
      noInstructionCycleHint: roadStateLookup.afterBlackClearKeys.has(roadKey)
        ? "after_black_clear"
        : option.noInstructionCycleHint,
    };
  });
}

function buildRoadStateGeojson(
  roadsGeojson: GeoJSON.FeatureCollection | null | undefined,
  selectedRoadKey: string,
  roadStateLookup: RoadStateLookup,
  pendingInstructionOverrides: PendingInstructionOverrides,
): GeoJSON.FeatureCollection {
  if (!roadsGeojson || !Array.isArray(roadsGeojson.features)) {
    return EMPTY_FEATURE_COLLECTION;
  }

  const features: RoadFeature[] = [];

  for (const feature of roadsGeojson.features) {
    if (!feature || typeof feature !== "object" || !isRoadFeature(feature)) {
      continue;
    }

    const props = readRoadProperties(feature);
    if (props.display_kind !== "operable") {
      continue;
    }

    const edgeKey = edgeIdToKey(edgeIdFromProperties(props));
    const override =
      pendingInstructionOverrides[edgeKey] ?? roadStateLookup.instructionByKey.get(edgeKey);
    const baseInstructionState = readInstructionState(props.instruction_state);
    const instructionState = override === undefined ? baseInstructionState : override;
    const failedPartial =
      roadStateLookup.failedPartialKeys.has(edgeKey) || readBoolean(props.is_failed_partial);
    const suppressedBase =
      roadStateLookup.suppressedBaseKeys.has(edgeKey) ||
      readBoolean(props.is_base_suppressed_by_final_state);
    const noInstructionCycleHint = roadStateLookup.afterBlackClearKeys.has(edgeKey)
      ? "after_black_clear"
      : readNoInstructionCycleHint(props.no_instruction_cycle_hint) ?? "";
    const isSelected = edgeKey === selectedRoadKey;
    const isOnCurrentRoute = readBoolean(props.is_on_current_route);
    const baseDisplayState = deriveRoadBaseDisplayState(props, isOnCurrentRoute);
    const diffDisplayState = deriveDiffDisplayState(instructionState);
    if (diffDisplayState === "transparent" && !failedPartial && !isSelected) {
      continue;
    }

    features.push({
      ...feature,
      properties: {
        ...props,
        display_kind: "operable",
        is_selected: isSelected,
        base_display_state: baseDisplayState,
        diff_display_state: diffDisplayState,
        display_state: deriveVisibleDisplayState(baseDisplayState, instructionState),
        instruction_state: instructionState,
        is_excluded: instructionState === "exclude",
        is_conditional: instructionState === "conditional",
        is_included: instructionState === "include",
        is_failed_included: instructionState === "include_failed",
        is_failed_partial: failedPartial,
        is_base_suppressed_by_final_state: suppressedBase,
        no_instruction_cycle_hint: noInstructionCycleHint,
      },
    });
  }

  return {
    ...roadsGeojson,
    features,
  };
}

function getOperableRoadFeatures(
  roadsGeojson: GeoJSON.FeatureCollection | null | undefined,
): RoadFeature[] {
  if (!roadsGeojson || !Array.isArray(roadsGeojson.features)) {
    return [];
  }

  return roadsGeojson.features.filter((feature): feature is RoadFeature => {
    return isRoadFeature(feature) && readRoadProperties(feature).display_kind === "operable";
  });
}

function getRouteSelectableFeatures(
  routeGeojson: GeoJSON.FeatureCollection | null | undefined,
  roadOptionKeys: Set<string>,
): RoadFeature[] {
  if (!routeGeojson || !Array.isArray(routeGeojson.features) || roadOptionKeys.size === 0) {
    return [];
  }

  return routeGeojson.features.filter((feature): feature is RoadFeature => {
    if (!isRoadFeature(feature)) {
      return false;
    }

    const props = readRoadProperties(feature);
    if (readBoolean(props.is_route_suppressed_by_final_state)) {
      return false;
    }

    const edgeId = edgeIdFromProperties(props);
    const edgeKey = edgeIdToKey(edgeId);
    const reversedEdgeKey = edgeIdToKey(reverseEdgeId(edgeId));
    return (
      edgeKey !== "____" &&
      (roadOptionKeys.has(edgeKey) || roadOptionKeys.has(reversedEdgeKey))
    );
  });
}

function getRouteRoadFeatures(
  routeGeojson: GeoJSON.FeatureCollection | null | undefined,
): RoadFeature[] {
  if (!routeGeojson || !Array.isArray(routeGeojson.features)) {
    return [];
  }

  return routeGeojson.features.filter((feature): feature is RoadFeature => {
    return (
      isRoadFeature(feature) &&
      !readBoolean(readRoadProperties(feature).is_route_suppressed_by_final_state)
    );
  });
}

function formatRoadState(isExcluded: boolean): string {
  return isExcluded ? "除雪対象外 / 使用禁止" : "使用可";
}

function formatDisplayState(displayState: DisplayState): string {
  if (displayState === "target") {
    return "Blue / target";
  }
  if (displayState === "connector") {
    return "Cyan / connector";
  }
  if (displayState === "return") {
    return "DeepSkyBlue / return";
  }
  if (displayState === "candidate") {
    return "DimGray / candidate";
  }
  if (displayState === "non_operable") {
    return "Gainsboro / non-operable";
  }
  if (displayState === "black") {
    return "Black / prohibit";
  }
  if (displayState === "orange") {
    return "Orange / conditional allow";
  }
  if (displayState === "magenta") {
    return "Magenta / target request";
  }
  if (displayState === "red") {
    return "Red / unmet target request";
  }
  return "none";
}

function normalizeRouteSegmentType(value: unknown): string {
  if (typeof value !== "string") {
    return "unknown";
  }

  const text = value.trim();
  if (text === "") {
    return "unknown";
  }
  return text === "access" ? "connector" : text;
}

function formatSegmentType(value: unknown): string {
  if (typeof value !== "string") {
    return "unknown";
  }

  const text = value.trim();
  if (text === "") {
    return "unknown";
  }

  const normalized = normalizeRouteSegmentType(text);
  return text === "access" ? "connector（旧 access）" : normalized;
}

function normalizeCoordinateToken(value: unknown): string {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return "nan";
  }

  const normalized = Math.abs(numberValue) < 1e-12 ? 0 : numberValue;
  return normalized.toFixed(7);
}

function getCoordinateSequences(feature: RoadFeature): GeoJSON.Position[][] {
  return feature.geometry.type === "LineString"
    ? [feature.geometry.coordinates]
    : feature.geometry.coordinates;
}

function serializeCoordinateSequence(coordinates: GeoJSON.Position[]): string {
  if (coordinates.length === 0) {
    return "";
  }

  const serialize = (points: GeoJSON.Position[]): string =>
    points
      .map(
        (position) =>
          `${normalizeCoordinateToken(position[0])},${normalizeCoordinateToken(position[1])}`,
      )
      .join(";");

  const forward = serialize(coordinates);
  const reversed = serialize([...coordinates].reverse());
  return forward < reversed ? forward : reversed;
}

function buildFeatureGeometrySignature(feature: RoadFeature): string {
  const parts = getCoordinateSequences(feature)
    .map((coordinates) => serializeCoordinateSequence(coordinates))
    .filter((value) => value !== "")
    .sort();

  return parts.join("||");
}

function buildOperableRoadGeometryIndex(
  operableRoadFeatures: RoadFeature[],
): Map<string, RoadFeature[]> {
  const geometryIndex = new Map<string, RoadFeature[]>();

  for (const feature of operableRoadFeatures) {
    const signature = buildFeatureGeometrySignature(feature);
    if (signature === "") {
      continue;
    }

    const existing = geometryIndex.get(signature);
    if (existing) {
      existing.push(feature);
    } else {
      geometryIndex.set(signature, [feature]);
    }
  }

  return geometryIndex;
}

function getFeatureEndpoints(feature: RoadFeature): {
  start: GeoJSON.Position | null;
  end: GeoJSON.Position | null;
} {
  const sequences = getCoordinateSequences(feature).filter((coordinates) => coordinates.length > 0);
  if (sequences.length === 0) {
    return { start: null, end: null };
  }

  const firstSequence = sequences[0];
  const lastSequence = sequences[sequences.length - 1];
  return {
    start: firstSequence[0] ?? null,
    end: lastSequence[lastSequence.length - 1] ?? null,
  };
}

function computePositionDistance(
  first: GeoJSON.Position | null,
  second: GeoJSON.Position | null,
): number {
  if (!first || !second || !isFinitePosition(first) || !isFinitePosition(second)) {
    return Number.POSITIVE_INFINITY;
  }

  const dx = Number(first[0]) - Number(second[0]);
  const dy = Number(first[1]) - Number(second[1]);
  return Math.hypot(dx, dy);
}

function computeEndpointMismatchScore(routeFeature: RoadFeature, roadFeature: RoadFeature): number {
  const routeEndpoints = getFeatureEndpoints(routeFeature);
  const roadEndpoints = getFeatureEndpoints(roadFeature);
  return (
    computePositionDistance(routeEndpoints.start, roadEndpoints.start) +
    computePositionDistance(routeEndpoints.end, roadEndpoints.end)
  );
}

function findGeometryMatchedOperableRoadFeature(
  routeFeature: RoadFeature,
  operableRoadGeometryIndex: Map<string, RoadFeature[]>,
): { feature: RoadFeature; detail: string } | null {
  const geometrySignature = buildFeatureGeometrySignature(routeFeature);
  if (geometrySignature === "") {
    return null;
  }

  const candidates = operableRoadGeometryIndex.get(geometrySignature) ?? [];
  if (candidates.length === 0) {
    return null;
  }

  let bestCandidate = candidates[0];
  let bestScore = computeEndpointMismatchScore(routeFeature, bestCandidate);

  for (const candidate of candidates.slice(1)) {
    const score = computeEndpointMismatchScore(routeFeature, candidate);
    if (score < bestScore) {
      bestCandidate = candidate;
      bestScore = score;
    }
  }

  return {
    feature: bestCandidate,
    detail:
      candidates.length === 1
        ? "geometry signature matched 1 candidate"
        : `geometry signature matched ${candidates.length} candidates; endpoint mismatch=${bestScore.toExponential(2)}`,
  };
}

function isFinitePosition(position: GeoJSON.Position): boolean {
  return Number.isFinite(Number(position[0])) && Number.isFinite(Number(position[1]));
}

function toPixelPoint(point: PixelPoint): PixelPoint {
  return { x: point.x, y: point.y };
}

function distancePointToSegment(point: PixelPoint, start: PixelPoint, end: PixelPoint): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;

  if (Math.abs(dx) < 1e-12 && Math.abs(dy) < 1e-12) {
    return Math.hypot(point.x - start.x, point.y - start.y);
  }

  const t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy);
  const clampedT = Math.max(0, Math.min(1, t));
  const closestX = start.x + dx * clampedT;
  const closestY = start.y + dy * clampedT;
  return Math.hypot(point.x - closestX, point.y - closestY);
}

function projectPosition(map: maplibregl.Map, position: GeoJSON.Position): PixelPoint | null {
  if (!isFinitePosition(position)) {
    return null;
  }

  const projected = map.project({
    lng: Number(position[0]),
    lat: Number(position[1]),
  });

  return {
    x: projected.x,
    y: projected.y,
  };
}

function computeLineDistancePx(
  map: maplibregl.Map,
  clickPoint: PixelPoint,
  coordinates: GeoJSON.Position[],
): number {
  if (coordinates.length < 2) {
    return Number.POSITIVE_INFINITY;
  }

  let bestDistance = Number.POSITIVE_INFINITY;

  for (let index = 0; index < coordinates.length - 1; index += 1) {
    const start = projectPosition(map, coordinates[index]);
    const end = projectPosition(map, coordinates[index + 1]);
    if (!start || !end) {
      continue;
    }

    const distance = distancePointToSegment(clickPoint, start, end);
    if (distance < bestDistance) {
      bestDistance = distance;
    }
  }

  return bestDistance;
}

function computeFeatureDistancePx(
  map: maplibregl.Map,
  clickPoint: PixelPoint,
  feature: RoadFeature,
): number {
  if (feature.geometry.type === "LineString") {
    return computeLineDistancePx(map, clickPoint, feature.geometry.coordinates);
  }

  let bestDistance = Number.POSITIVE_INFINITY;

  for (const line of feature.geometry.coordinates) {
    const distance = computeLineDistancePx(map, clickPoint, line);
    if (distance < bestDistance) {
      bestDistance = distance;
    }
  }

  return bestDistance;
}

function findNearestOperableRoadFeature(
  map: maplibregl.Map,
  clickPoint: PixelPoint,
  operableRoadFeatures: RoadFeature[],
  maxDistancePx: number,
): FeatureDistanceMatch | null {
  let bestMatch: FeatureDistanceMatch | null = null;

  for (const feature of operableRoadFeatures) {
    const distancePx = computeFeatureDistancePx(map, clickPoint, feature);
    if (!Number.isFinite(distancePx) || distancePx > maxDistancePx) {
      continue;
    }

    if (bestMatch === null || distancePx < bestMatch.distancePx) {
      bestMatch = { feature, distancePx };
    }
  }

  return bestMatch;
}

function findOperableRoadMatchesWithinDistancePx(
  map: maplibregl.Map,
  clickPoint: PixelPoint,
  operableRoadFeatures: RoadFeature[],
  maxDistancePx: number,
): FeatureDistanceMatch[] {
  const matches: FeatureDistanceMatch[] = [];

  for (const feature of operableRoadFeatures) {
    const distancePx = computeFeatureDistancePx(map, clickPoint, feature);
    if (!Number.isFinite(distancePx) || distancePx > maxDistancePx) {
      continue;
    }
    matches.push({ feature, distancePx });
  }

  matches.sort((left, right) => left.distancePx - right.distancePx);
  return matches;
}

function findNearestInstructionOverlayRoadFeature(
  map: maplibregl.Map,
  clickPoint: PixelPoint,
  _operableRoadFeatures: RoadFeature[],
  maxDistancePx: number,
): FeatureDistanceMatch | null {
  if (INSTRUCTION_OVERLAY_LAYER_IDS.length === 0) {
    return null;
  }

  const queryBounds: [[number, number], [number, number]] = [
    [
      clickPoint.x - INSTRUCTION_OVERLAY_QUERY_TOLERANCE_PX,
      clickPoint.y - INSTRUCTION_OVERLAY_QUERY_TOLERANCE_PX,
    ],
    [
      clickPoint.x + INSTRUCTION_OVERLAY_QUERY_TOLERANCE_PX,
      clickPoint.y + INSTRUCTION_OVERLAY_QUERY_TOLERANCE_PX,
    ],
  ];

  const renderedFeatures = map.queryRenderedFeatures(queryBounds, {
    layers: INSTRUCTION_OVERLAY_LAYER_IDS,
  });
  const candidateByRoadKey = new Map<string, FeatureDistanceMatch>();

  for (const renderedFeature of renderedFeatures) {
    if (!isRoadFeature(renderedFeature as GeoJSON.Feature)) {
      continue;
    }

    const feature = renderedFeature as RoadFeature;
    if (!isInstructionOverlayState(getFeatureDisplayState(feature))) {
      continue;
    }

    const roadKey = edgeIdToKey(edgeIdFromProperties(readRoadProperties(feature)));
    if (roadKey === "____") {
      continue;
    }

    const distancePx = computeFeatureDistancePx(map, clickPoint, feature);
    if (!Number.isFinite(distancePx) || distancePx > maxDistancePx) {
      continue;
    }

    const existing = candidateByRoadKey.get(roadKey);
    if (!existing || distancePx < existing.distancePx) {
      candidateByRoadKey.set(roadKey, { feature, distancePx });
    }
  }

  let bestMatch: FeatureDistanceMatch | null = null;
  for (const candidate of candidateByRoadKey.values()) {
    if (!bestMatch || candidate.distancePx < bestMatch.distancePx) {
      bestMatch = candidate;
    }
  }

  return bestMatch;
}

function findClickedVisibleRoadFeature(
  map: maplibregl.Map,
  clickPoint: PixelPoint,
): FeatureDistanceMatch | null {
  if (CLICKED_VISIBLE_ROAD_LAYER_IDS.length === 0) {
    return null;
  }

  const queryBounds: [[number, number], [number, number]] = [
    [
      clickPoint.x - CLICKED_VISIBLE_ROAD_QUERY_TOLERANCE_PX,
      clickPoint.y - CLICKED_VISIBLE_ROAD_QUERY_TOLERANCE_PX,
    ],
    [
      clickPoint.x + CLICKED_VISIBLE_ROAD_QUERY_TOLERANCE_PX,
      clickPoint.y + CLICKED_VISIBLE_ROAD_QUERY_TOLERANCE_PX,
    ],
  ];

  const renderedFeatures = map.queryRenderedFeatures(queryBounds, {
    layers: CLICKED_VISIBLE_ROAD_LAYER_IDS,
  });

  for (const renderedFeature of renderedFeatures) {
    if (!isRoadFeature(renderedFeature as GeoJSON.Feature)) {
      continue;
    }

    const feature = renderedFeature as RoadFeature;
    const distancePx = computeFeatureDistancePx(map, clickPoint, feature);
    if (!Number.isFinite(distancePx) || distancePx > CLICKED_VISIBLE_ROAD_QUERY_TOLERANCE_PX) {
      continue;
    }

    return { feature, distancePx };
  }

  return null;
}

function buildSelectedRoadDescription(roadOption: RoadOption | null): string {
  return roadOption ? roadOption.label : "none";
}

function createComponentInstanceId(): string {
  return `d3-map-${Math.random().toString(36).slice(2, 10)}`;
}

export default function MapClickComponent(props: Props): React.ReactElement {
  const {
    initialViewState,
    currentStartPoint,
    candidateStartPoint,
    resetViewNonce,
    roadsGeojson,
    roadState,
    routeGeojson,
    routeCycleGuide,
    showRouteCycleGuide = true,
    debugMode = false,
    pendingSyncNonce = 0,
    lineStyles: lineStylesInput,
    height = 600,
    onEvent,
  } = props;

  const mapRef = useRef<MapRef | null>(null);
  const componentInstanceIdRef = useRef<string>(createComponentInstanceId());
  const emittedEventNonceRef = useRef<number>(0);
  const lastHandledPendingSyncNonceRef = useRef<number>(0);
  const lastClearedInstructionSyncAckNonceRef = useRef<number>(0);
  const renderCountRef = useRef<number>(0);
  const mapViewStateRef = useRef<MapViewState>(buildMapViewState(initialViewState));
  const initialViewStateRef = useRef<ViewStateInput>(initialViewState);
  const resetResizeFrameRef = useRef<number | null>(null);
  const roadsGeojsonCacheRef = useRef<{
    version: string;
    data: GeoJSON.FeatureCollection;
  }>({ version: "", data: EMPTY_FEATURE_COLLECTION });
  const routeGeojsonCacheRef = useRef<{
    version: string;
    data: GeoJSON.FeatureCollection;
  }>({ version: "", data: EMPTY_FEATURE_COLLECTION });
  renderCountRef.current += 1;
  initialViewStateRef.current = initialViewState;
  const roadsGeojsonVersion = roadState?.roads_geojson_version ?? "roads-unversioned";
  const routeGeojsonVersion = roadState?.route_geojson_version ?? "route-unversioned";
  const stableRoadsGeojson = useMemo(() => {
    if (roadsGeojson && roadsGeojsonCacheRef.current.version !== roadsGeojsonVersion) {
      roadsGeojsonCacheRef.current = {
        version: roadsGeojsonVersion,
        data: roadsGeojson,
      };
    }
    return roadsGeojsonCacheRef.current.data;
  }, [roadsGeojson, roadsGeojsonVersion]);
  const stableRouteGeojson = useMemo(() => {
    if (routeGeojson && routeGeojsonCacheRef.current.version !== routeGeojsonVersion) {
      routeGeojsonCacheRef.current = {
        version: routeGeojsonVersion,
        data: routeGeojson,
      };
    }
    return routeGeojsonCacheRef.current.data;
  }, [routeGeojson, routeGeojsonVersion]);
  const lineStyles = useMemo(() => mergeLineStyles(lineStylesInput), [lineStylesInput]);
  const routeCycleGuideStyle = useMemo(
    () => normalizeRouteCycleGuideStyle(lineStylesInput),
    [lineStylesInput],
  );
  const showBasemap = useMemo(() => normalizeShowBasemap(lineStylesInput), [lineStylesInput]);
  const backgroundRoadLayer = useMemo(() => buildBackgroundRoadLayer(lineStyles), [lineStyles]);
  const operableRoadBaseLayer = useMemo(() => buildOperableRoadBaseLayer(lineStyles), [lineStyles]);
  const routeLayer = useMemo(() => buildRouteLayer(lineStyles), [lineStyles]);
  const conditionalRoadTopLayer = useMemo(() => buildConditionalRoadTopLayer(lineStyles), [lineStyles]);
  const excludedRoadTopLayer = useMemo(() => buildExcludedRoadTopLayer(lineStyles), [lineStyles]);
  const includedRoadTopLayer = useMemo(() => buildIncludedRoadTopLayer(lineStyles), [lineStyles]);
  const failedIncludedRoadTopLayer = useMemo(
    () => buildFailedIncludedRoadTopLayer(lineStyles),
    [lineStyles],
  );
  const failedPartialRoadTopLayer = useMemo(
    () => buildFailedPartialRoadTopLayer(lineStyles),
    [lineStyles],
  );

  const [mapViewState, setMapViewState] = useState<MapViewState>(() =>
    buildMapViewState(initialViewState),
  );
  const [mapOverlayNonce, setMapOverlayNonce] = useState<number>(0);
  const [selectedRoadKey, setSelectedRoadKey] = useState<string>("");
  const [pendingInstructionOverrides, setPendingInstructionOverrides] =
    useState<PendingInstructionOverrides>({});
  const [noInstructionCycleHints, setNoInstructionCycleHints] =
    useState<NoInstructionCycleHints>({});
  const [lastMapPickMessage, setLastMapPickMessage] = useState<string>(
    "地図をクリックすると、許容距離内の最近傍 operable 道路を選択します。",
  );

  const [lastEmittedEventType, setLastEmittedEventType] = useState<string>("none");
  const [lastEmittedEventNonce, setLastEmittedEventNonce] = useState<number>(0);
  const [lastRouteHitSegmentType, setLastRouteHitSegmentType] = useState<string>("none");
  const [lastClickedFeatureDisplayKind, setLastClickedFeatureDisplayKind] = useState<string>("none");
  const [lastClickedRoadIsOperableCandidate, setLastClickedRoadIsOperableCandidate] =
    useState<string>("unknown");
  const [lastRouteResolutionMethod, setLastRouteResolutionMethod] = useState<string>("none");
  const [lastRouteResolutionDetail, setLastRouteResolutionDetail] = useState<string>("none");
  const [lastResolvedEdgeKey, setLastResolvedEdgeKey] = useState<string>("none");
  const [lastResolvedRoadLabel, setLastResolvedRoadLabel] = useState<string>("none");
  const [lastResolvedDisplayState, setLastResolvedDisplayState] = useState<string>("none");
  const [lastRouteGeometrySignature, setLastRouteGeometrySignature] = useState<string>("none");
  const [lastNearbyOperableCandidateCount, setLastNearbyOperableCandidateCount] = useState<number>(0);
  const [lastNearestOperableDistance, setLastNearestOperableDistance] = useState<string>("none");

  const applyWheelZoomSensitivity = (): void => {
    const scrollZoom = mapRef.current?.getMap().scrollZoom;
    scrollZoom?.setWheelZoomRate(WHEEL_ZOOM_RATE);
    scrollZoom?.setZoomRate(TRACKPAD_ZOOM_RATE);
  };

  const setCurrentMapViewState = (nextViewState: MapViewState): void => {
    mapViewStateRef.current = nextViewState;
    setMapViewState(nextViewState);
  };

  const clearResetResizeFrame = (): void => {
    if (resetResizeFrameRef.current === null) {
      return;
    }

    window.cancelAnimationFrame(resetResizeFrameRef.current);
    resetResizeFrameRef.current = null;
  };

  const refreshOverlayProjection = (): void => {
    setMapOverlayNonce((value) => value + 1);
  };

  useEffect(() => {
    const resetViewState = buildMapViewState(initialViewStateRef.current);
    setCurrentMapViewState(resetViewState);

    clearResetResizeFrame();
    resetResizeFrameRef.current = window.requestAnimationFrame(() => {
      resetResizeFrameRef.current = null;
      mapRef.current?.getMap().resize();
      refreshOverlayProjection();
    });

    return () => {
      clearResetResizeFrame();
    };
  }, [resetViewNonce]);

  useEffect(() => {
    return () => {
      clearResetResizeFrame();
    };
  }, []);

  const baseRoadOptions = useMemo(() => buildRoadOptions(stableRoadsGeojson), [stableRoadsGeojson]);
  const roadStateLookup = useMemo(() => buildRoadStateLookup(roadState), [roadState]);

  const effectiveRoadOptions = useMemo(() => {
    return buildEffectiveRoadOptions(baseRoadOptions, roadStateLookup, pendingInstructionOverrides);
  }, [baseRoadOptions, roadStateLookup, pendingInstructionOverrides]);

  const roadOptionByKey = useMemo(() => {
    return new Map(effectiveRoadOptions.map((option) => [edgeIdToKey(option.edgeId), option]));
  }, [effectiveRoadOptions]);

  const selectedRoadOptionFromProps = useMemo(() => {
    return effectiveRoadOptions.find((option) => option.isSelected) ?? null;
  }, [effectiveRoadOptions]);

  const selectedRoadKeyFromProps = useMemo(() => {
    return selectedRoadOptionFromProps ? edgeIdToKey(selectedRoadOptionFromProps.edgeId) : "";
  }, [selectedRoadOptionFromProps]);

  useEffect(() => {
    setSelectedRoadKey((currentSelectedRoadKey) =>
      currentSelectedRoadKey === selectedRoadKeyFromProps
        ? currentSelectedRoadKey
        : selectedRoadKeyFromProps,
    );
  }, [selectedRoadKeyFromProps]);

  useEffect(() => {
    setPendingInstructionOverrides((currentOverrides) => {
      if (Object.keys(currentOverrides).length === 0) {
        return currentOverrides;
      }

      const nextOverrides: PendingInstructionOverrides = { ...currentOverrides };
      let changed = false;

      for (const option of baseRoadOptions) {
        const roadKey = edgeIdToKey(option.edgeId);
        if (!Object.prototype.hasOwnProperty.call(nextOverrides, roadKey)) {
          continue;
        }

        const serverInstructionState =
          roadStateLookup.instructionByKey.get(roadKey) ?? option.instructionState;
        if (nextOverrides[roadKey] === serverInstructionState) {
          delete nextOverrides[roadKey];
          changed = true;
        }
      }

      return changed ? nextOverrides : currentOverrides;
    });
  }, [baseRoadOptions, roadStateLookup]);

  useEffect(() => {
    const ackNonce = Number(roadState?.instruction_sync_ack_nonce ?? 0);
    if (!Number.isFinite(ackNonce) || ackNonce <= 0) {
      return;
    }
    if (lastClearedInstructionSyncAckNonceRef.current === ackNonce) {
      return;
    }

    lastClearedInstructionSyncAckNonceRef.current = ackNonce;
    setPendingInstructionOverrides((currentOverrides) =>
      Object.keys(currentOverrides).length === 0 ? currentOverrides : {},
    );
    setNoInstructionCycleHints((currentHints) =>
      Object.keys(currentHints).length === 0 ? currentHints : {},
    );
  }, [roadState?.instruction_sync_ack_nonce]);

  const displayRoadsGeojson = useMemo(() => {
    return stableRoadsGeojson;
  }, [stableRoadsGeojson]);

  const roadStateGeojson = useMemo(() => {
    return buildRoadStateGeojson(
      stableRoadsGeojson,
      selectedRoadKey,
      roadStateLookup,
      pendingInstructionOverrides,
    );
  }, [stableRoadsGeojson, selectedRoadKey, roadStateLookup, pendingInstructionOverrides]);

  const operableRoadFeatures = useMemo(() => {
    return getOperableRoadFeatures(stableRoadsGeojson);
  }, [stableRoadsGeojson]);

  const operableRoadGeometryIndex = useMemo(() => {
    return buildOperableRoadGeometryIndex(operableRoadFeatures);
  }, [operableRoadFeatures]);

  const routeSelectableFeatures = useMemo(() => {
    return getRouteSelectableFeatures(stableRouteGeojson, new Set(roadOptionByKey.keys()));
  }, [stableRouteGeojson, roadOptionByKey]);

  const routeRoadFeatures = useMemo(() => {
    return getRouteRoadFeatures(stableRouteGeojson);
  }, [stableRouteGeojson]);

  const selectedRoadOption = selectedRoadOptionFromProps ?? roadOptionByKey.get(selectedRoadKey) ?? null;
  const toggleTargetRoadOption = selectedRoadOption ?? selectedRoadOptionFromProps ?? null;

  const getEffectiveInstructionState = (
    roadKey: string,
    fallback: InstructionState,
  ): InstructionState => {
    return roadStateLookup.instructionByKey.get(roadKey) ?? fallback;
  };

  const queueInstructionOverride = (roadKey: string, nextInstructionState: InstructionState): void => {
    setPendingInstructionOverrides((currentOverrides) => ({
      ...currentOverrides,
      [roadKey]: nextInstructionState,
    }));
  };

  const updateNoInstructionCycleHint = (
    roadKey: string,
    currentDisplayState: DisplayState,
    nextInstructionState: InstructionState,
  ): void => {
    setNoInstructionCycleHints((currentHints) => {
      const nextHints: NoInstructionCycleHints = { ...currentHints };
      if (currentDisplayState === "black" && nextInstructionState === "none") {
        nextHints[roadKey] = "after_black_clear";
      } else {
        delete nextHints[roadKey];
      }
      return nextHints;
    });
  };

  const isOperableCandidateFeature = (feature: RoadFeature | null): boolean => {
    if (!feature) {
      return false;
    }

    const props = readRoadProperties(feature);
    const displayKind = readDisplayKind(props.display_kind);
    if (displayKind === "operable") {
      return true;
    }

    const edgeOption = findRoadOptionByEdgeId(roadOptionByKey, edgeIdFromProperties(props));
    if (edgeOption.edgeKey !== "____" && edgeOption.option) {
      return true;
    }

    if (findGeometryMatchedOperableRoadFeature(feature, operableRoadGeometryIndex)) {
      return true;
    }

    if (displayKind === "route") {
      const segmentType = normalizeRouteSegmentType(props.segment_type);
      return segmentType === "target" || segmentType === "connector";
    }

    return false;
  };

  const buildEventEnvelope = (viewState: MapViewState = mapViewState): EventEnvelope => {
    emittedEventNonceRef.current += 1;
    const eventNonce = emittedEventNonceRef.current;
    setLastEmittedEventNonce(eventNonce);
    return {
      event_nonce: eventNonce,
      component_instance_id: componentInstanceIdRef.current,
      map_view_state: {
        lat: viewState.latitude,
        lon: viewState.longitude,
        zoom: viewState.zoom,
        bearing: viewState.bearing,
        pitch: viewState.pitch,
      },
    };
  };

  const emitMapViewUpdate = (viewState: MapViewState): void => {
    const payload: MapViewUpdateEvent = {
      ...buildEventEnvelope(viewState),
      event_type: "map_view_update",
    };

    setLastEmittedEventType(payload.event_type);
    console.log("[MapClickComponent:map] emit map_view_update", payload);
    onEvent(payload);
  };

  const emitRoadSelectForEdgeId = (edgeId: EdgeId): void => {
    const payload: RoadSelectEvent = {
      ...buildEventEnvelope(),
      event_type: "road_select",
      edge_id: edgeId,
    };

    setLastEmittedEventType(payload.event_type);
    console.log("[MapClickComponent:map] emit road_select", payload);
    onEvent(payload);
  };

  const emitRoadToggleForEdgeId = (
    edgeId: EdgeId,
    displayState: DisplayState,
    nextInstructionState?: InstructionState,
  ): void => {
    const payload: RoadToggleEvent = {
      ...buildEventEnvelope(),
      event_type: "road_toggle",
      edge_id: edgeId,
      display_state: displayState,
      next_instruction_state: nextInstructionState,
    };

    setLastEmittedEventType(payload.event_type);
    console.log("[MapClickComponent:map] emit road_toggle", payload);
    onEvent(payload);
  };

  const emitPendingInstructionSync = (syncNonce: number): void => {
    const instructions = Object.entries(pendingInstructionOverrides)
      .map(([roadKey, instructionState]) => {
        const roadOption = roadOptionByKey.get(roadKey);
        if (!roadOption) {
          return null;
        }
        return {
          edge_id: roadOption.edgeId,
          instruction_state: instructionState,
        };
      })
      .filter(
        (
          item,
        ): item is {
          edge_id: EdgeId;
          instruction_state: InstructionState;
        } => item !== null,
      );

    const payload: RoadInstructionsSyncEvent = {
      ...buildEventEnvelope(),
      event_type: "road_instructions_sync",
      instructions,
      pending_count: instructions.length,
      sync_nonce: syncNonce,
    };

    setLastEmittedEventType(payload.event_type);
    console.log("[MapClickComponent:map] emit road_instructions_sync", payload);
    onEvent(payload);
  };

  useEffect(() => {
    if (pendingSyncNonce <= 0) {
      return;
    }
    if (lastHandledPendingSyncNonceRef.current === pendingSyncNonce) {
      return;
    }

    lastHandledPendingSyncNonceRef.current = pendingSyncNonce;
    emitPendingInstructionSync(pendingSyncNonce);
  }, [pendingSyncNonce, pendingInstructionOverrides, roadOptionByKey]);

  const emitStartPointSet = (point?: { lat: number; lon: number }): void => {
    const lat =
      point && Number.isFinite(point.lat)
        ? point.lat
        : Number.isFinite(mapViewState.latitude)
          ? mapViewState.latitude
          : 43.426;
    const lon =
      point && Number.isFinite(point.lon)
        ? point.lon
        : Number.isFinite(mapViewState.longitude)
          ? mapViewState.longitude
          : 141.886;

    const payload: StartPointSetEvent = {
      ...buildEventEnvelope(),
      event_type: "start_point_set",
      lat,
      lon,
    };

    setLastEmittedEventType(payload.event_type);
    console.log("[MapClickComponent:map] emit start_point_set", payload);
    onEvent(payload);
  };

  const emitStartPointRestoreToRecalculationBaseline = (): void => {
    const payload: StartPointRestoreToRecalculationBaselineEvent = {
      ...buildEventEnvelope(),
      event_type: "start_point_restore_to_recalculation_baseline",
    };

    setLastEmittedEventType(payload.event_type);
    console.log(
      "[MapClickComponent:map] emit start_point_restore_to_recalculation_baseline",
      payload,
    );
    onEvent(payload);
  };

  const resolveRouteHitToRoadMatch = (
    map: maplibregl.Map,
    clickPoint: PixelPoint,
    routeHitMatch: FeatureDistanceMatch,
  ): RouteResolution => {
    const routeProps = readRoadProperties(routeHitMatch.feature);
    const routeSegmentType = normalizeRouteSegmentType(routeProps.segment_type);
    const routeEdgeId = edgeIdFromProperties(routeProps);
    const routeRoadKey = edgeIdToKey(routeEdgeId);

    const routeRoadOption = findRoadOptionByEdgeId(roadOptionByKey, routeEdgeId);
    if (routeRoadOption.edgeKey !== "____" && routeRoadOption.option) {
      return {
        match: routeHitMatch,
        method: routeRoadOption.reversed ? "route_edge_id_reverse" : "route_edge_id",
        detail: `segment_type=${routeSegmentType}; route edge_id matched ${routeRoadOption.edgeKey}`,
      };
    }

    const geometryMatch = findGeometryMatchedOperableRoadFeature(
      routeHitMatch.feature,
      operableRoadGeometryIndex,
    );
    if (geometryMatch) {
      return {
        match: {
          feature: geometryMatch.feature,
          distancePx: computeFeatureDistancePx(map, clickPoint, geometryMatch.feature),
        },
        method: "route_geometry_match",
        detail: `segment_type=${routeSegmentType}; ${geometryMatch.detail}`,
      };
    }

    const routeFallback = findNearestOperableRoadFeature(
      map,
      clickPoint,
      routeSelectableFeatures,
      ROUTE_FALLBACK_THRESHOLD_PX,
    );
    if (routeFallback) {
      return {
        match: routeFallback,
        method: "route_click_fallback",
        detail: `segment_type=${routeSegmentType}; nearest selectable route ${routeFallback.distancePx.toFixed(2)}px`,
      };
    }

    const geometrySignature = buildFeatureGeometrySignature(routeHitMatch.feature);
    const geometryCandidateCount =
      geometrySignature === "" ? 0 : (operableRoadGeometryIndex.get(geometrySignature)?.length ?? 0);
    const routeEdgeDetail =
      routeRoadKey === "____" ? "route edge_id missing" : `route edge_id ${routeRoadKey} not operable`;

    return {
      match: null,
      method: "route_unresolved",
      detail: `segment_type=${routeSegmentType}; ${routeEdgeDetail}; geometry_candidates=${geometryCandidateCount}; no selectable route within ${ROUTE_FALLBACK_THRESHOLD_PX}px`,
    };
  };

  const emitRoadSelect = (): void => {
    if (!selectedRoadOption) {
      return;
    }

    setSelectedRoadKey(edgeIdToKey(selectedRoadOption.edgeId));
    setLastMapPickMessage(`${selectedRoadOption.label} を選択しました。`);
    emitRoadSelectForEdgeId(selectedRoadOption.edgeId);
  };

  const emitRoadToggle = (): void => {
    if (!toggleTargetRoadOption) {
      return;
    }

    const roadKey = edgeIdToKey(toggleTargetRoadOption.edgeId);
    const currentDisplayState = getOptionDisplayState(toggleTargetRoadOption);
    const nextInstructionState = getNextInstructionState(currentDisplayState, {
      noInstructionCycleHint:
        noInstructionCycleHints[roadKey] ?? toggleTargetRoadOption.noInstructionCycleHint,
    });

    queueInstructionOverride(roadKey, nextInstructionState);
    updateNoInstructionCycleHint(roadKey, currentDisplayState, nextInstructionState);
    setSelectedRoadKey(roadKey);
    setLastResolvedEdgeKey(roadKey);
    setLastResolvedDisplayState(currentDisplayState);
    setLastMapPickMessage(
      nextInstructionState === "exclude"
        ? `${toggleTargetRoadOption.label} を除雪対象外 / 使用禁止に切り替えました。`
        : `${toggleTargetRoadOption.label} を使用可に戻しました。`,
    );
    if (debugMode) {
      emitRoadToggleForEdgeId(
        toggleTargetRoadOption.edgeId,
        currentDisplayState,
        nextInstructionState,
      );
    } else {
      setLastEmittedEventType("local_pending");
    }
  };

  const handleMapMove = (event: ViewStateChangeEvent): void => {
    const nextPitch = event.viewState.pitch ?? 0;
    setCurrentMapViewState({
      latitude: event.viewState.latitude,
      longitude: event.viewState.longitude,
      zoom: event.viewState.zoom,
      bearing: event.viewState.bearing ?? 0,
      pitch: nextPitch,
    });
  };

  const handleMapMoveEnd = (event: ViewStateChangeEvent): void => {
    const nextPitch = event.viewState.pitch ?? 0;
    const nextViewState: MapViewState = {
      latitude: event.viewState.latitude,
      longitude: event.viewState.longitude,
      zoom: event.viewState.zoom,
      bearing: event.viewState.bearing ?? 0,
      pitch: nextPitch,
    };
    if (Math.abs(nextPitch) > ROUTE_CYCLE_GUIDE_MAX_PITCH_DEGREES) {
      mapRef.current?.getMap().easeTo({ pitch: 0, duration: 0 });
      nextViewState.pitch = 0;
    }
    setCurrentMapViewState(nextViewState);
    if (debugMode) {
      emitMapViewUpdate(nextViewState);
    } else {
      setLastEmittedEventType("local_view");
    }
  };

  const handleMapClick = (event: MapMouseEvent): void => {
    if (event.originalEvent.button !== 0) {
      return;
    }

    const map = mapRef.current?.getMap();
    if (!map) {
      return;
    }

    if (event.originalEvent.ctrlKey === true) {
      if (event.originalEvent.shiftKey === true) {
        setLastMapPickMessage(
          "Ctrl + Shift + click -> restore start point to recalculation baseline",
        );
        emitStartPointRestoreToRecalculationBaseline();
        return;
      }

      emitStartPointSet({
        lat: event.lngLat.lat,
        lon: event.lngLat.lng,
      });
      setLastMapPickMessage(
        `Ctrl + click -> start point ${event.lngLat.lat.toFixed(6)}, ${event.lngLat.lng.toFixed(6)}`,
      );
      return;
    }

    const clickPoint = toPixelPoint({ x: event.point.x, y: event.point.y });
    const clickedVisibleFeature = findClickedVisibleRoadFeature(map, clickPoint);
    const clickedVisibleProps = clickedVisibleFeature
      ? readRoadProperties(clickedVisibleFeature.feature)
      : null;
    const clickedFeatureDisplayKind = clickedVisibleFeature
      ? readDisplayKind(clickedVisibleProps?.display_kind)
      : "none";
    const clickedRoadIsOperableCandidate = clickedVisibleFeature
      ? (isOperableCandidateFeature(clickedVisibleFeature.feature) ? "yes" : "no")
      : "unknown";
    setLastClickedFeatureDisplayKind(clickedFeatureDisplayKind);
    setLastClickedRoadIsOperableCandidate(clickedRoadIsOperableCandidate);

    const routeHit = findNearestOperableRoadFeature(
      map,
      clickPoint,
      routeRoadFeatures,
      ROUTE_PICK_THRESHOLD_PX,
    );
    const routeHitProps = routeHit ? readRoadProperties(routeHit.feature) : null;
    const routeHitSegmentType = normalizeRouteSegmentType(routeHitProps?.segment_type);
    setLastRouteHitSegmentType(routeHit ? routeHitSegmentType : "none");
    setLastRouteGeometrySignature(routeHit ? buildFeatureGeometrySignature(routeHit.feature) : "none");

    const nearbyOperableMatches = findOperableRoadMatchesWithinDistancePx(
      map,
      clickPoint,
      operableRoadFeatures,
      ROUTE_FALLBACK_THRESHOLD_PX,
    );
    const nearestOperableMatch = findNearestOperableRoadFeature(
      map,
      clickPoint,
      operableRoadFeatures,
      Number.POSITIVE_INFINITY,
    );
    const nearestOperableDistanceText = nearestOperableMatch
      ? `${nearestOperableMatch.distancePx.toFixed(2)}px`
      : "none";
    setLastNearbyOperableCandidateCount(nearbyOperableMatches.length);
    setLastNearestOperableDistance(nearestOperableDistanceText);

    let hitResult: FeatureDistanceMatch | null = null;
    let resolutionMethod = "none";
    let resolutionDetail = "none";
    const overlayHit = findNearestInstructionOverlayRoadFeature(
      map,
      clickPoint,
      operableRoadFeatures,
      ROAD_PICK_THRESHOLD_PX,
    );

    if (overlayHit) {
      hitResult = overlayHit;
      const overlayEdgeKey = edgeIdToKey(edgeIdFromProperties(readRoadProperties(overlayHit.feature)));
      resolutionMethod = "instruction_overlay_direct";
      resolutionDetail = `display_state=${getFeatureDisplayState(overlayHit.feature)}; edge_key=${overlayEdgeKey}; rendered instruction overlay ${overlayHit.distancePx.toFixed(2)}px`;
    } else if (routeHit) {
      const routeResolution = resolveRouteHitToRoadMatch(map, clickPoint, routeHit);
      hitResult = routeResolution.match;
      resolutionMethod = routeResolution.method;
      resolutionDetail = routeResolution.detail;
    } else {
      resolutionMethod = "no_route_hit";
      resolutionDetail = `no route feature within ${ROUTE_PICK_THRESHOLD_PX}px`;
    }

    if (!hitResult) {
      const roadFallback = findNearestOperableRoadFeature(
        map,
        clickPoint,
        operableRoadFeatures,
        ROAD_PICK_THRESHOLD_PX,
      );
      if (roadFallback) {
        hitResult = roadFallback;
        resolutionMethod = routeHit ? "operable_click_fallback" : "road_click_direct";
        resolutionDetail = routeHit
          ? `${resolutionDetail}; nearest operable road ${roadFallback.distancePx.toFixed(2)}px`
          : `nearest operable road ${roadFallback.distancePx.toFixed(2)}px`;
      }
    }

    if (!hitResult) {
      setLastRouteResolutionMethod(resolutionMethod);
      setLastRouteResolutionDetail(
        routeHit
          ? `${resolutionDetail}; nearby_operable_candidates=${nearbyOperableMatches.length}; nearest_operable_distance=${nearestOperableDistanceText}`
          : `${resolutionDetail}; nearby_operable_candidates=${nearbyOperableMatches.length}; nearest_operable_distance=${nearestOperableDistanceText}; no operable road within ${ROAD_PICK_THRESHOLD_PX}px`,
      );
      setLastResolvedEdgeKey("none");
      setLastResolvedRoadLabel("none");
      setLastResolvedDisplayState("none");
      setLastEmittedEventType("none");
    setLastMapPickMessage(
        routeHit
          ? `青ルートを hit しましたが、operable 道路へ結び付けられませんでした。${resolutionDetail}`
          : `クリック位置から青ルート ${ROUTE_PICK_THRESHOLD_PX}px / 道路 ${ROAD_PICK_THRESHOLD_PX}px 以内に選択可能な道路がありません。`,
      );
      return;
    }

    const edgeId = edgeIdFromProperties(readRoadProperties(hitResult.feature));
    const roadOptionMatch = findRoadOptionByEdgeId(roadOptionByKey, edgeId);
    const nextSelectedRoadKey = roadOptionMatch.edgeKey;
    const matchedRoadOption = roadOptionMatch.option;
    if (!matchedRoadOption) {
      setLastRouteResolutionMethod("resolved_without_road_option");
      setLastRouteResolutionDetail(
        `${resolutionDetail}; resolved edge_key=${edgeIdToKey(edgeId)} not found in road options`,
      );
      setLastResolvedEdgeKey(edgeIdToKey(edgeId));
      setLastResolvedRoadLabel("none");
      setLastResolvedDisplayState("none");
      setLastEmittedEventType("none");
      setLastMapPickMessage(
        `道路候補までは解決できましたが、operable road option に存在しません。edge_key=${nextSelectedRoadKey}`,
      );
      return;
    }

    setLastRouteResolutionMethod(resolutionMethod);
    setLastRouteResolutionDetail(resolutionDetail);
    setLastResolvedEdgeKey(nextSelectedRoadKey);
    setLastResolvedRoadLabel(matchedRoadOption.label);
    const currentDisplayState =
      resolutionMethod === "route_edge_id" ||
      resolutionMethod === "route_edge_id_reverse" ||
      resolutionMethod === "route_geometry_match" ||
      resolutionMethod === "route_click_fallback"
        ? routeHit
          ? getFeatureDisplayState(routeHit.feature)
          : getFeatureDisplayState(hitResult.feature)
        : getFeatureDisplayState(hitResult.feature);
    const nextInstructionState = getNextInstructionState(currentDisplayState, {
      shiftKey: event.originalEvent.shiftKey === true,
      noInstructionCycleHint:
        noInstructionCycleHints[nextSelectedRoadKey] ?? matchedRoadOption.noInstructionCycleHint,
    });

    if (event.originalEvent.shiftKey === true && matchedRoadOption.instructionState === "none") {
      updateNoInstructionCycleHint(nextSelectedRoadKey, currentDisplayState, nextInstructionState);
      setSelectedRoadKey(nextSelectedRoadKey);
      setLastResolvedDisplayState(currentDisplayState);
      setLastMapPickMessage(
        `${buildSelectedRoadDescription(matchedRoadOption)} -> reset (no diff instruction)`,
      );
      setLastEmittedEventType("none");
      return;
    }

    queueInstructionOverride(nextSelectedRoadKey, nextInstructionState);
    updateNoInstructionCycleHint(
      nextSelectedRoadKey,
      currentDisplayState,
      nextInstructionState,
    );
    setSelectedRoadKey(nextSelectedRoadKey);
    setLastResolvedDisplayState(currentDisplayState);
    setLastMapPickMessage(
      nextInstructionState === "exclude"
        ? `${buildSelectedRoadDescription(matchedRoadOption)} -> Black (${hitResult.distancePx.toFixed(2)}px)`
        : nextInstructionState === "conditional"
          ? `${buildSelectedRoadDescription(matchedRoadOption)} -> Orange (${hitResult.distancePx.toFixed(2)}px)`
          : nextInstructionState === "include"
            ? `${buildSelectedRoadDescription(matchedRoadOption)} -> Magenta (${hitResult.distancePx.toFixed(2)}px)`
            : `${buildSelectedRoadDescription(matchedRoadOption)} -> reset (${hitResult.distancePx.toFixed(2)}px)`,
    );
    if (debugMode) {
      emitRoadToggleForEdgeId(roadOptionMatch.edgeId, currentDisplayState, nextInstructionState);
    } else {
      setLastEmittedEventType("local_pending");
    }
    return;
    /*
      setLastMapPickMessage(
        nextExcluded
          ? `${buildSelectedRoadDescription(matchedRoadOption)} を再クリックしたため、除雪対象外 / 使用禁止に切り替えました。`
          : `${buildSelectedRoadDescription(matchedRoadOption)} を再クリックしたため、使用可に戻しました。`,
      );
      emitRoadToggleForEdgeId(edgeId);
      return;
    }

    setSelectedRoadKey(nextSelectedRoadKey);
    setLastMapPickMessage(
      `${buildSelectedRoadDescription(matchedRoadOption)} を選択しました。距離 ${hitResult.distancePx.toFixed(2)}px`,
    );
    emitRoadSelectForEdgeId(edgeId);
    */
  };

  const roadFeatureCount = Array.isArray(stableRoadsGeojson.features)
    ? stableRoadsGeojson.features.length
    : 0;
  const routeFeatureCount = Array.isArray(stableRouteGeojson.features)
    ? stableRouteGeojson.features.length
    : 0;
  const routeSelectableFeatureCount = routeSelectableFeatures.length;
  const routeRoadFeatureCount = routeRoadFeatures.length;
  const shouldShowRouteCycleGuide =
    Boolean(showRouteCycleGuide) &&
    Boolean(routeCycleGuide?.path?.length) &&
    Math.abs(mapViewState.pitch) <= ROUTE_CYCLE_GUIDE_MAX_PITCH_DEGREES;
  const mapHeight = Math.max(height, 360);
  const currentStartPointPixel = useMemo((): PixelPoint | null => {
    if (!currentStartPoint || !mapRef.current) {
      return null;
    }
    return projectGuidePoint(mapRef.current, currentStartPoint);
  }, [currentStartPoint, mapOverlayNonce, mapViewState]);
  const candidateStartPointPixel = useMemo((): PixelPoint | null => {
    if (!candidateStartPoint || !mapRef.current) {
      return null;
    }
    return projectGuidePoint(mapRef.current, candidateStartPoint);
  }, [candidateStartPoint, mapOverlayNonce, mapViewState]);
  const routeCycleGuideSegments = useMemo((): RouteCyclePixelSegment[] => {
    if (!shouldShowRouteCycleGuide) {
      return [];
    }
    const rawPassSegments = routeCycleGuide?.raw_pass_segments ?? [];
    const isRawPassDisplay = rawPassSegments.length > 0;
    const segments = isRawPassDisplay ? rawPassSegments : routeCycleGuide?.segments ?? [];
    if (!segments.length || !mapRef.current) {
      return [];
    }
    const laneOffsetScale = getRouteCycleGuideLaneOffsetZoomScale(mapViewState.zoom);

    return segments
      .map((segment) => {
        const projectedPoints = segment.path
          .map((point) => projectGuidePoint(mapRef.current as MapRef, point))
          .filter((point): point is PixelPoint => point !== null);
        if (projectedPoints.length < 2) {
          return null;
        }
        const offsetPx = routeCycleGuideSegmentOffsetPx(
          segment.offset_lane,
          segment.edge_repeat_count,
          routeCycleGuideStyle,
          laneOffsetScale,
        );

        return {
          points: projectedPoints,
          basePoints: projectedPoints,
          edgeOffsetsPx: Array(Math.max(1, projectedPoints.length - 1)).fill(offsetPx),
          edgeSegmentOrders: Array(Math.max(1, projectedPoints.length - 1)).fill(
            segment.segment_order ?? null,
          ),
          segmentOrder: segment.segment_order ?? null,
          passFromNode: segment.pass_from_node ?? null,
          passToNode: segment.pass_to_node ?? null,
          edgeRepeatCount: segment.edge_repeat_count,
          edgeRepeatIndex: segment.edge_repeat_index,
          directionPassCount: segment.direction_pass_count ?? segment.edge_repeat_count,
          directionPassIndex: segment.direction_pass_index ?? segment.edge_repeat_index,
          offsetLane: segment.offset_lane,
          isRawPassSegment: isRawPassDisplay,
          isClosedLoop: isClosedRouteCycleSegment(projectedPoints),
        };
      })
      .filter((segment): segment is RouteCyclePixelSegment => segment !== null);
  }, [
    routeCycleGuide,
    shouldShowRouteCycleGuide,
    mapOverlayNonce,
    mapViewState.latitude,
    mapViewState.longitude,
    mapViewState.zoom,
    mapViewState.bearing,
    mapViewState.pitch,
    routeCycleGuideStyle,
  ]);
  const routeCycleGuidePoints = useMemo((): PixelPoint[] => {
    if (!shouldShowRouteCycleGuide) {
      return [];
    }
    const path = routeCycleGuide?.path;
    if (!path || path.length < 2 || !mapRef.current) {
      return [];
    }

    return path
      .map((point) => projectGuidePoint(mapRef.current as MapRef, point))
      .filter((point): point is PixelPoint => point !== null);
  }, [
    routeCycleGuide,
    shouldShowRouteCycleGuide,
    mapOverlayNonce,
    mapViewState.latitude,
    mapViewState.longitude,
    mapViewState.zoom,
    mapViewState.bearing,
    mapViewState.pitch,
  ]);
  const routeCycleGuideOverlay = useMemo(() => {
    const useSegments = routeCycleGuideSegments.length > 0;
    const preferRawPassChain =
      useSegments && routeCycleGuideSegments.some((segment) => segment.isRawPassSegment);
    const runs = useSegments
      ? buildRouteCycleGuideRuns(routeCycleGuideSegments, preferRawPassChain)
      : [];
    const displayRuns = buildOffsetRouteCycleGuideRuns(runs);
    const joins = useSegments ? buildContinuousRouteCycleOffsetJoins(displayRuns) : [];
    const drawablePoints = useSegments
      ? displayRuns
          .flatMap((run) => run.points)
          .concat(joins.flatMap((join) =>
            join.cubicControls ? [...join.points, ...join.cubicControls] : join.points
          ))
      : routeCycleGuidePoints;
    if (drawablePoints.length < 2) {
      return null;
    }

    const padding = 24;
    const xs = drawablePoints.map((point) => point.x);
    const ys = drawablePoints.map((point) => point.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const left = Math.max(0, minX - padding);
    const top = Math.max(0, minY - padding);
    const width = Math.max(1, maxX - minX + padding * 2);
    const height = Math.max(1, maxY - minY + padding * 2);
    const fallbackPointText = pointText(routeCycleGuidePoints, left, top);
    const firstOrder = parseRouteCycleSegmentOrder(routeCycleGuide?.first_segment_order) ?? 1;
    const lastOrder = parseRouteCycleSegmentOrder(routeCycleGuide?.last_segment_order);
    const segments = displayRuns.flatMap((run) =>
      buildRouteCycleDisplaySegments(
        run,
        left,
        top,
        firstOrder,
        lastOrder,
        routeCycleGuideStyle.lineColor,
      ),
    );
    const joinSegments = joins.map((join) => ({
      pathD: routeCycleJoinPathText(join, left, top),
    }));
    const firstSegment = routeCycleGuideSegments.find(
      (segment) => parseRouteCycleSegmentOrder(segment.segmentOrder) === firstOrder,
    );
    const lastSegment = routeCycleGuideSegments.find(
      (segment) => parseRouteCycleSegmentOrder(segment.segmentOrder) === lastOrder,
    );
    const currentStartProjected =
      currentStartPoint && mapRef.current
        ? projectGuidePoint(mapRef.current, currentStartPoint)
        : null;
    const firstSegmentOffsetPoints =
      firstSegment
        ? findRouteCycleRunSegmentPoints(displayRuns, firstSegment.segmentOrder)
        : null;
    const startDebugConnector =
      firstSegmentOffsetPoints && currentStartProjected
        ? pointText([currentStartProjected, firstSegmentOffsetPoints[0]], left, top)
        : null;
    const lastSegmentOffsetPoints =
      lastSegment
        ? findRouteCycleRunSegmentPoints(displayRuns, lastSegment.segmentOrder)
        : null;
    const arrivalDebugConnector =
      lastSegmentOffsetPoints && currentStartProjected
        ? pointText(
            [
              lastSegmentOffsetPoints[lastSegmentOffsetPoints.length - 1],
              currentStartProjected,
            ],
            left,
            top,
          )
        : null;
    const specialArrows = [
      firstSegmentOffsetPoints
        ? {
            color: ROUTE_CYCLE_START_DEBUG_COLOR,
            arrow: buildRouteCycleGuideArrow(firstSegmentOffsetPoints, 0.5, routeCycleGuideStyle),
          }
        : null,
      lastSegmentOffsetPoints
        ? {
            color: ROUTE_CYCLE_ARRIVAL_DEBUG_COLOR,
            arrow: buildRouteCycleGuideArrow(lastSegmentOffsetPoints, 0.5, routeCycleGuideStyle),
          }
        : null,
    ]
      .filter(
        (entry): entry is { color: string; arrow: RouteCycleGuideArrow } =>
          entry !== null && entry.arrow !== null,
      )
      .map(({ color, arrow }) => ({
        color,
        points: arrow.points.map((point) => ({
          x: point.x - left,
          y: point.y - top,
        })),
      }));
    const cumulativeArrows = useSegments
      ? buildRouteCycleGuideArrowsByCumulativeDistance(displayRuns, routeCycleGuideStyle)
      : [];
    const closedLoopArrows = useSegments
      ? displayRuns
          .filter((run) => run.isClosedLoop)
          .map((run) => buildRouteCycleGuideArrow(run.points, 0.5, routeCycleGuideStyle))
          .filter((arrow): arrow is RouteCycleGuideArrow => arrow !== null)
      : [];
    const arrows = cumulativeArrows.concat(closedLoopArrows).map((arrow) => ({
          x: arrow.x - left,
          y: arrow.y - top,
          angle: arrow.angle,
          points: arrow.points.map((point) => ({
            x: point.x - left,
            y: point.y - top,
          })),
        }));
    return {
      left,
      top,
      width,
      height,
      fallbackPointText,
      segments,
      joinSegments,
      startDebugConnector,
      arrivalDebugConnector,
      specialArrows,
      arrows,
      useSegments,
    };
  }, [
    routeCycleGuideSegments,
    routeCycleGuidePoints,
    routeCycleGuideStyle,
    routeCycleGuide,
    currentStartPoint,
  ]);
  const displayLegendItems: LegendItem[] = [
    { label: "Blue: target", color: lineStyles.target.lineColor, width: lineStyles.target.lineWidth },
    {
      label: "Cyan: connector",
      color: lineStyles.connector.lineColor,
      width: lineStyles.connector.lineWidth,
    },
    {
      label: "DeepSkyBlue: return",
      color: lineStyles.return.lineColor,
      width: lineStyles.return.lineWidth,
    },
    {
      label: "DimGray: candidate",
      color: lineStyles.candidate.lineColor,
      width: lineStyles.candidate.lineWidth,
    },
    {
      label: "Gainsboro: non-operable",
      color: lineStyles.nonOperable.lineColor,
      width: lineStyles.nonOperable.lineWidth,
    },
  ];
  const diffLegendItems: LegendItem[] = [
    {
      label: "Black: prohibit",
      color: lineStyles.strongProhibit.lineColor,
      width: lineStyles.strongProhibit.lineWidth,
    },
    {
      label: "Orange: conditional allow",
      color: lineStyles.conditionalAllow.lineColor,
      width: lineStyles.conditionalAllow.lineWidth,
    },
    {
      label: "Magenta: target request",
      color: lineStyles.targetRequest.lineColor,
      width: lineStyles.targetRequest.lineWidth,
    },
    {
      label: "Red: unmet target request",
      color: lineStyles.unmetTarget.lineColor,
      width: lineStyles.unmetTarget.lineWidth,
    },
    {
      label: "Red dotted: partial unmet target",
      color: lineStyles.partialUnmetTarget.lineColor,
      width: lineStyles.partialUnmetTarget.lineWidth,
      lineStyle: "dashed",
    },
  ];

  return (
    <div
      style={{
        width: "100%",
        minHeight: `${height}px`,
        background: "#f3f4f6",
        border: "1px solid #d1d5db",
        borderRadius: "8px",
        padding: "16px",
        boxSizing: "border-box",
      }}
    >
      <div style={{ display: "none", fontWeight: 700, marginBottom: "8px" }}>
        Map Click Component / map + road_select + road_toggle
      </div>

      <div
        style={{
          display: "none",
          fontSize: "14px",
          marginBottom: "12px",
          lineHeight: 1.6,
          padding: "10px 12px",
          borderRadius: "8px",
          background: "#ffffff",
          border: "1px solid #d1d5db",
        }}
      >
        左クリックは差分指示の確定操作です。色状態は
        <code> Black → Transparent → Magenta → Orange → Black </code>
        の順で循環します。<br />
        <code>Red</code> は左クリックで <code>Magenta</code> に戻ります。<br />
        <code>Shift + 左クリック</code> は、直近の再計算直後の表示状態へ戻します。
      </div>

      <div style={{ display: "none", fontSize: "13px", marginBottom: "12px", lineHeight: 1.6 }}>
        <code>Ctrl + 左クリック</code>: クリック地点を現在の出発点に変更 /
        <code> Ctrl + Shift + 左クリック</code>: 最後に再計算が正常完了した時点の出発点へ戻す
      </div>

      <div style={{ display: "none", fontSize: "14px", marginBottom: "12px", lineHeight: 1.6 }}>
        通常左クリックで、許容距離 10px 以内の最近傍 operable 道路を選択して
        <code>road_select</code> を送ります。
        <br />
        青い現在ルート上の道路も、対応する operable 道路キーが取れる場合は選択対象に含めます。
        <br />
        同じ道路を再クリックすると、除雪対象外 / 使用禁止 と 使用可 を切り替えます。
      </div>

      <div
        style={{
          display: "none",
          gap: "12px",
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: "16px",
        }}
      >
        <button
          type="button"
          onClick={emitStartPointSet}
          style={{
            padding: "10px 16px",
            borderRadius: "8px",
            border: "1px solid #9ca3af",
            cursor: "pointer",
            fontWeight: 600,
            background: "#ffffff",
          }}
        >
          start_point_set を送る
        </button>

        <select
          value={selectedRoadKey}
          onChange={(event) => setSelectedRoadKey(event.target.value)}
          style={{
            minWidth: "360px",
            padding: "8px",
            borderRadius: "8px",
            border: "1px solid #9ca3af",
            background: "#ffffff",
          }}
        >
          <option value="">道路を選択してください</option>
          {effectiveRoadOptions.map((option) => (
            <option key={edgeIdToKey(option.edgeId)} value={edgeIdToKey(option.edgeId)}>
              {option.label}
              {option.isExcluded ? " [除雪対象外]" : " [使用可]"}
              {option.isSelected ? " [selected]" : ""}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={emitRoadSelect}
          disabled={!selectedRoadOption}
          style={{
            padding: "10px 16px",
            borderRadius: "8px",
            border: "1px solid #9ca3af",
            cursor: selectedRoadOption ? "pointer" : "not-allowed",
            fontWeight: 600,
            background: "#ffffff",
          }}
        >
          road_select を送る
        </button>

        <button
          type="button"
          onClick={emitRoadToggle}
          disabled={!toggleTargetRoadOption}
          style={{
            padding: "10px 16px",
            borderRadius: "8px",
            border: "1px solid #9ca3af",
            cursor: toggleTargetRoadOption ? "pointer" : "not-allowed",
            fontWeight: 600,
            background: "#ffffff",
          }}
        >
          road_toggle を送る
        </button>
      </div>

      <div
        style={{
          marginBottom: "12px",
          padding: "10px 12px",
          borderRadius: "8px",
          background: "#ffffff",
          border: "1px solid #d1d5db",
          fontSize: "13px",
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: "8px" }}>Display Layer</div>
        <div style={{ display: "flex", gap: "14px", flexWrap: "wrap", marginBottom: "10px" }}>
          {displayLegendItems.map((item) => (
            <div
              key={item.label}
              style={{ display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span
                style={{
                  width: "28px",
                  height: "0",
                  borderTop: `${item.width}px ${item.lineStyle ?? "solid"} ${item.color}`,
                  borderRadius: "999px",
                  display: "inline-block",
                }}
              />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        <div style={{ fontWeight: 700, marginBottom: "8px" }}>Diff Layer</div>
        <div style={{ display: "flex", gap: "14px", flexWrap: "wrap", marginBottom: "10px" }}>
          {diffLegendItems.map((item) => (
            <div
              key={item.label}
              style={{ display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span
                style={{
                  width: "28px",
                  height: "0",
                  borderTop: `${item.width}px ${item.lineStyle ?? "solid"} ${item.color}`,
                  borderRadius: "999px",
                  display: "inline-block",
                }}
              />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "none" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "28px",
              height: "0",
              borderRadius: "999px",
              display: "inline-block",
            }}
          />
          <span>青: 現在ルート</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "28px",
              height: "0",
              borderRadius: "999px",
              display: "inline-block",
            }}
          />
          <span>黒: 除雪対象外 / 使用禁止</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "28px",
              height: "0",
              borderRadius: "999px",
              display: "inline-block",
            }}
          />
          <span>灰: その他道路</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "28px",
              height: "0",
              borderRadius: "999px",
              display: "inline-block",
            }}
          />
          <span>選択中道路: 補助情報</span>
        </div>
      </div>

      <div
        style={{
          position: "relative",
          marginBottom: "16px",
          border: "1px solid #d1d5db",
          borderRadius: "8px",
          overflow: "hidden",
        }}
      >
        <MapComponent
          ref={mapRef}
          mapLib={maplibregl}
          mapStyle={MAP_STYLE}
          {...mapViewState}
          boxZoom={false}
          onMove={handleMapMove}
          onLoad={() => {
            applyWheelZoomSensitivity();
            refreshOverlayProjection();
          }}
          onMoveEnd={handleMapMoveEnd}
          onClick={handleMapClick}
          style={{
            width: "100%",
            height: `${mapHeight}px`,
          }}
        >
          <NavigationControl position="top-right" showCompass={false} />

          {showBasemap ? (
            <Source
              id={BASEMAP_SOURCE_ID}
              type="raster"
              tiles={["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]}
              tileSize={256}
              attribution="© OpenStreetMap contributors"
            >
              <Layer
                id={BASEMAP_LAYER_ID}
                type="raster"
                paint={{
                  "raster-opacity": 0.72,
                }}
              />
            </Source>
          ) : null}

          <Source id={ROAD_SOURCE_ID} type="geojson" data={displayRoadsGeojson}>
            <Layer {...backgroundRoadLayer} />
            <Layer {...operableRoadBaseLayer} />
          </Source>

          <Source id="route-source" type="geojson" data={stableRouteGeojson}>
            <Layer {...routeLayer} />
          </Source>

          <Source id={ROAD_STATE_SOURCE_ID} type="geojson" data={roadStateGeojson}>
            <Layer {...excludedRoadTopLayer} />
            <Layer {...conditionalRoadTopLayer} />
            <Layer {...includedRoadTopLayer} />
            <Layer {...failedIncludedRoadTopLayer} />
            <Layer {...failedPartialRoadTopLayer} />
          </Source>

        </MapComponent>

        {routeCycleGuideOverlay ? (
          <svg
            aria-hidden="true"
            width={routeCycleGuideOverlay.width}
            height={routeCycleGuideOverlay.height}
            style={{
              position: "absolute",
              left: `${routeCycleGuideOverlay.left}px`,
              top: `${routeCycleGuideOverlay.top}px`,
              width: `${routeCycleGuideOverlay.width}px`,
              height: `${routeCycleGuideOverlay.height}px`,
              pointerEvents: "none",
              zIndex: 1,
            }}
          >
            {routeCycleGuideOverlay.useSegments ? (
              <>
                {routeCycleGuideOverlay.segments.map((segment, index) => (
                  <polyline
                    key={`route-cycle-segment-${index}`}
                    points={segment.pointText}
                    fill="none"
                    stroke={segment.color}
                    strokeWidth={
                      segment.edgeRepeatCount >= 2
                        ? routeCycleGuideStyle.lineWidth + 0.4
                        : routeCycleGuideStyle.lineWidth
                    }
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeOpacity={1}
                  />
                ))}
                {routeCycleGuideOverlay.joinSegments.map((join, index) => (
                  <path
                    key={`route-cycle-join-${index}`}
                    d={join.pathD}
                    fill="none"
                    stroke={routeCycleGuideStyle.lineColor}
                    strokeWidth={routeCycleGuideStyle.lineWidth}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeOpacity={1}
                  />
                ))}
                {routeCycleGuideOverlay.startDebugConnector ? (
                  <polyline
                    points={routeCycleGuideOverlay.startDebugConnector}
                    fill="none"
                    stroke={ROUTE_CYCLE_START_DEBUG_COLOR}
                    strokeWidth={routeCycleGuideStyle.lineWidth + 1.4}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeOpacity={1}
                  />
                ) : null}
                {routeCycleGuideOverlay.arrivalDebugConnector ? (
                  <polyline
                    points={routeCycleGuideOverlay.arrivalDebugConnector}
                    fill="none"
                    stroke={ROUTE_CYCLE_ARRIVAL_DEBUG_COLOR}
                    strokeWidth={routeCycleGuideStyle.lineWidth + 1.4}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeOpacity={1}
                  />
                ) : null}
                {routeCycleGuideOverlay.arrows.map((arrow, index) => (
                  <polygon
                    key={`route-cycle-arrow-${index}`}
                    points={polygonPointText(arrow.points)}
                    fill={routeCycleGuideStyle.marker.fillColor}
                    stroke={routeCycleGuideStyle.marker.strokeColor}
                    strokeWidth="0"
                    opacity="1"
                  />
                ))}
                {routeCycleGuideOverlay.specialArrows.map((arrow, index) => (
                  <polygon
                    key={`route-cycle-special-arrow-${index}`}
                    points={polygonPointText(arrow.points)}
                    fill={arrow.color}
                    stroke={arrow.color}
                    strokeWidth="0"
                    opacity="1"
                  />
                ))}
              </>
            ) : (
              <>
                <polyline
                  points={routeCycleGuideOverlay.fallbackPointText}
                  fill="none"
                  stroke={routeCycleGuideStyle.lineColor}
                  strokeWidth={routeCycleGuideStyle.lineWidth}
                  strokeLinecap="round"
                  strokeLinejoin="bevel"
                  strokeOpacity="1"
                />
              </>
            )}
          </svg>
        ) : null}

        {currentStartPointPixel ? (
          <div
            style={{
              position: "absolute",
              left: `${currentStartPointPixel.x}px`,
              top: `${currentStartPointPixel.y}px`,
              width: "16px",
              height: "16px",
              borderRadius: "999px",
              background: "#ef4444",
              border: "2px solid #ffffff",
              transform: "translate(-50%, -50%)",
              pointerEvents: "none",
              zIndex: 3,
              boxShadow:
                "0 0 0 3px rgba(0, 102, 255, 0.28), 0 0 0 1px rgba(0, 0, 0, 0.25)",
            }}
            title="current start point"
          />
        ) : null}

        {candidateStartPointPixel ? (
          <div
            style={{
              position: "absolute",
              left: `${candidateStartPointPixel.x}px`,
              top: `${candidateStartPointPixel.y}px`,
              width: "18px",
              height: "18px",
              borderRadius: "999px",
              background: "#f59e0b",
              border: "2px solid #ffffff",
              transform: "translate(-50%, -50%)",
              pointerEvents: "none",
              zIndex: 3,
              boxShadow: "0 0 0 1px rgba(0, 0, 0, 0.25)",
            }}
            title="candidate start point"
          />
        ) : null}
      </div>

      <div
        style={{
          fontSize: "13px",
          marginBottom: "16px",
          lineHeight: 1.6,
          padding: "10px 12px",
          borderRadius: "8px",
          background: "#ffffff",
          border: "1px solid #d1d5db",
        }}
      >
        <div>
          <strong>map click</strong>: {lastMapPickMessage}
        </div>
        <div>
          左クリックの基本遷移は <code>Black → Transparent → Magenta → Orange → Black</code>
          です。
        </div>
        <div>
          <code>Red</code> は左クリックで <code>Magenta</code> に戻ります。
        </div>
        <div>
          <code>Shift + 左クリック</code> は、直近の再計算直後の表示状態へ戻します。
        </div>
      </div>

      <div style={{ display: "none", fontSize: "13px", marginBottom: "16px", lineHeight: 1.5 }}>
        <div>
          <strong>map click</strong>: {lastMapPickMessage}
        </div>
        <div>
          <strong>road_toggle</strong> は、選択中の道路を再クリックしたときにも送れます。
        </div>
        <div>黒は選択の有無に関係なく除雪対象外 / 使用禁止を表します。</div>
      </div>

      <div style={{ display: "none" }}>
        選択中の道路をもう一度クリックすると、<code>road_toggle</code> を送って
        「除雪対象外 / 使用可」を切り替えます。
      </div>

      <style>
        {`
          .maplibregl-canvas,
          .maplibregl-canvas-container.maplibregl-interactive {
            cursor: default !important;
          }
        `}
      </style>

      <div
        style={{
          display: "none",
          gridTemplateColumns: "220px 1fr",
          gap: "8px 12px",
          fontSize: "13px",
          lineHeight: 1.5,
        }}
      >
        <div>initialViewState</div>
        <div>{`${initialViewState.lat}, ${initialViewState.lon}, zoom=${initialViewState.zoom}`}</div>

        <div>mapViewState</div>
        <div>{`${mapViewState.latitude}, ${mapViewState.longitude}, zoom=${mapViewState.zoom.toFixed(2)}`}</div>

        <div>currentStartPoint</div>
        <div>{currentStartPoint ? `${currentStartPoint.lat}, ${currentStartPoint.lon}` : "null"}</div>

        <div>candidateStartPoint</div>
        <div>{candidateStartPoint ? `${candidateStartPoint.lat}, ${candidateStartPoint.lon}` : "null"}</div>

        <div>resetViewNonce</div>
        <div>{String(resetViewNonce)}</div>

        <div>component instance id</div>
        <div>{componentInstanceIdRef.current}</div>

        <div>local render count</div>
        <div>{String(renderCountRef.current)}</div>

        <div>roadsGeojson features</div>
        <div>{String(roadFeatureCount)}</div>

        <div>operable road options</div>
        <div>{String(effectiveRoadOptions.length)}</div>

        <div>selected road option</div>
        <div>{selectedRoadOption ? selectedRoadOption.label : "none"}</div>

        <div>selected road from props</div>
        <div>{selectedRoadOptionFromProps ? selectedRoadOptionFromProps.label : "none"}</div>

        <div>selected road state</div>
        <div>{selectedRoadOption ? formatDisplayState(getOptionDisplayState(selectedRoadOption)) : "none"}</div>

        <div>last resolved edge_key</div>
        <div>{lastResolvedEdgeKey}</div>

        <div>last resolved display_state</div>
        <div>{lastResolvedDisplayState}</div>

        <div>pending instruction overrides</div>
        <div>{String(Object.keys(pendingInstructionOverrides).length)}</div>

        <div>routeGeojson features</div>
        <div>{String(routeFeatureCount)}</div>

        <div>route road features</div>
        <div>{String(routeRoadFeatureCount)}</div>

        <div>route selectable features</div>
        <div>{String(routeSelectableFeatureCount)}</div>

        <div>last emitted event type</div>
        <div>{lastEmittedEventType}</div>

        <div>last emitted event nonce</div>
        <div>{String(lastEmittedEventNonce)}</div>

        <div>clicked feature display_kind</div>
        <div>{lastClickedFeatureDisplayKind}</div>

        <div>clicked road is operable candidate</div>
        <div>{lastClickedRoadIsOperableCandidate}</div>

        <div>last route hit segment_type</div>
        <div>{lastRouteHitSegmentType}</div>

        <div>last route resolution method</div>
        <div>{lastRouteResolutionMethod}</div>

        <div>last route resolution detail</div>
        <div>{lastRouteResolutionDetail}</div>

        <div>last resolved road</div>
        <div>{lastResolvedRoadLabel}</div>

        <div>last route geometry signature</div>
        <div>{lastRouteGeometrySignature}</div>

        <div>nearby operable candidates (28px)</div>
        <div>{String(lastNearbyOperableCandidateCount)}</div>

        <div>nearest operable distance</div>
        <div>{lastNearestOperableDistance}</div>

        <div>routeCycleGuide</div>
        <div>{`show=${String(shouldShowRouteCycleGuide)}`}</div>
      </div>
    </div>
  );
}

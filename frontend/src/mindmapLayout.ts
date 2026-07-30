export type MindMapLayoutNode = {
  id: string;
  width: number;
  height: number;
};

export type MindMapLayoutEdge = {
  source: string;
  target: string;
};

export type MindMapLayoutSide = "root" | "right" | "left";

export type MindMapLayoutPoint = {
  x: number;
  y: number;
};

export type MindMapLayoutBox = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

export type MindMapLayoutResult = {
  positions: Map<string, MindMapLayoutPoint>;
  boxes: Map<string, MindMapLayoutBox>;
  sideByNode: Map<string, MindMapLayoutSide>;
  rootChildrenRight: string[];
  rootChildrenLeft: string[];
  subtreeExtents: Map<string, number>;
  canvasWidth: number;
  canvasHeight: number;
};

export type MindMapVisibilityResult = {
  visibleNodeIds: string[];
  hiddenCounts: Map<string, number>;
};

export const mindMapLabelMaxLines = ({
  isRoot,
  isBranch,
  hasMedia,
}: {
  isRoot: boolean;
  isBranch: boolean;
  hasMedia: boolean;
}) => {
  if (isRoot) return 8;
  if (hasMedia) return 2;
  return isBranch ? 5 : 6;
};

type OrderedTree = {
  nodeIds: string[];
  children: Map<string, string[]>;
  parent: Map<string, string>;
  depth: Map<string, number>;
  traversal: string[];
};

const unique = (values: string[]) => [...new Set(values)];

const buildOrderedTree = (
  nodeIds: string[],
  edges: MindMapLayoutEdge[],
  rootId: string,
): OrderedTree => {
  const orderedIds = unique(nodeIds);
  const nodeSet = new Set(orderedIds);
  if (!nodeSet.has(rootId)) throw new Error(`布局根节点不存在: ${rootId}`);

  const rawChildren = new Map(
    orderedIds.map((nodeId) => [nodeId, [] as string[]]),
  );
  const rawParent = new Map<string, string>();
  for (const edge of edges) {
    if (
      !nodeSet.has(edge.source) ||
      !nodeSet.has(edge.target) ||
      edge.source === edge.target ||
      edge.target === rootId ||
      rawParent.has(edge.target)
    ) {
      continue;
    }
    rawParent.set(edge.target, edge.source);
    rawChildren.get(edge.source)?.push(edge.target);
  }

  const children = new Map(
    orderedIds.map((nodeId) => [nodeId, [] as string[]]),
  );
  const parent = new Map<string, string>();
  const depth = new Map<string, number>([[rootId, 0]]);
  const traversal = [rootId];
  const visited = new Set<string>([rootId]);

  const walkFrom = (seed: string) => {
    const stack = [seed];
    while (stack.length) {
      const nodeId = stack.pop();
      if (!nodeId) continue;
      const discovered: string[] = [];
      for (const childId of rawChildren.get(nodeId) || []) {
        if (visited.has(childId)) continue;
        visited.add(childId);
        parent.set(childId, nodeId);
        depth.set(childId, (depth.get(nodeId) || 0) + 1);
        children.get(nodeId)?.push(childId);
        traversal.push(childId);
        discovered.push(childId);
      }
      for (let index = discovered.length - 1; index >= 0; index -= 1) {
        stack.push(discovered[index]);
      }
    }
  };

  walkFrom(rootId);
  while (visited.size < orderedIds.length) {
    const unvisited = orderedIds.filter((nodeId) => !visited.has(nodeId));
    const unvisitedSet = new Set(unvisited);
    const seed =
      unvisited.find((nodeId) => {
        const rawParentId = rawParent.get(nodeId);
        return !rawParentId || !unvisitedSet.has(rawParentId);
      }) || unvisited[0];
    visited.add(seed);
    parent.set(seed, rootId);
    depth.set(seed, 1);
    children.get(rootId)?.push(seed);
    traversal.push(seed);
    walkFrom(seed);
  }

  return {
    nodeIds: orderedIds,
    children,
    parent,
    depth,
    traversal,
  };
};

const stackCenters = (
  nodeIds: string[],
  extents: Map<string, number>,
  verticalGap: number,
) => {
  const centers = new Map<string, number>();
  if (!nodeIds.length) return centers;
  const total =
    nodeIds.reduce((sum, nodeId) => sum + (extents.get(nodeId) || 0), 0) +
    verticalGap * (nodeIds.length - 1);
  let cursor = -total / 2;
  for (const nodeId of nodeIds) {
    const extent = extents.get(nodeId) || 0;
    centers.set(nodeId, cursor + extent / 2);
    cursor += extent + verticalGap;
  }
  return centers;
};

const splitRootChildren = (
  rootChildren: string[],
  extents: Map<string, number>,
  verticalGap: number,
  rightRatio: number,
) => {
  if (!rootChildren.length) return { right: [] as string[], left: [] as string[] };
  const totalHeight =
    rootChildren.reduce(
      (sum, nodeId) => sum + (extents.get(nodeId) || 0),
      0,
    ) +
    verticalGap * (rootChildren.length - 1);
  const rightBudget = totalHeight * rightRatio;
  const right: string[] = [];
  const left: string[] = [];
  let usedHeight = 0;
  let switched = false;
  for (const nodeId of rootChildren) {
    const addition =
      (extents.get(nodeId) || 0) + (right.length ? verticalGap : 0);
    if (!switched && (!right.length || usedHeight + addition <= rightBudget)) {
      right.push(nodeId);
      usedHeight += addition;
    } else {
      switched = true;
      left.push(nodeId);
    }
  }
  return { right, left };
};

export const computeMindMapLayout = ({
  nodes,
  edges,
  rootId,
  rightRatio = 0.62,
  verticalGap = 32,
  horizontalGap = 72,
  margin = 72,
  titleSpace = 84,
  minimumCanvasWidth = 1200,
  minimumCanvasHeight = 720,
}: {
  nodes: MindMapLayoutNode[];
  edges: MindMapLayoutEdge[];
  rootId: string;
  rightRatio?: number;
  verticalGap?: number;
  horizontalGap?: number;
  margin?: number;
  titleSpace?: number;
  minimumCanvasWidth?: number;
  minimumCanvasHeight?: number;
}): MindMapLayoutResult => {
  if (rightRatio <= 0 || rightRatio > 1) {
    throw new Error("rightRatio 必须在 (0, 1] 内");
  }
  if (verticalGap < 24 || horizontalGap < 24) {
    throw new Error("布局节点安全间距不能小于 24px");
  }

  const tree = buildOrderedTree(
    nodes.map((node) => node.id),
    edges,
    rootId,
  );
  const sizeById = new Map(nodes.map((node) => [node.id, node]));
  const subtreeExtents = new Map<string, number>();
  for (const nodeId of [...tree.traversal].reverse()) {
    const node = sizeById.get(nodeId);
    if (!node || node.width <= 0 || node.height <= 0) {
      throw new Error(`节点缺少有效尺寸: ${nodeId}`);
    }
    const childIds = tree.children.get(nodeId) || [];
    const childrenHeight =
      childIds.reduce(
        (sum, childId) => sum + (subtreeExtents.get(childId) || 0),
        0,
      ) + verticalGap * Math.max(childIds.length - 1, 0);
    subtreeExtents.set(nodeId, Math.max(node.height, childrenHeight));
  }

  const maxWidthByDepth = new Map<number, number>();
  let maxDepth = 0;
  for (const nodeId of tree.nodeIds) {
    const nodeDepth = tree.depth.get(nodeId) || 0;
    const node = sizeById.get(nodeId);
    if (!node) throw new Error(`节点缺少有效尺寸: ${nodeId}`);
    maxDepth = Math.max(maxDepth, nodeDepth);
    maxWidthByDepth.set(
      nodeDepth,
      Math.max(maxWidthByDepth.get(nodeDepth) || 0, node.width),
    );
  }
  const columnX = new Map<number, number>([[0, 0]]);
  for (let nodeDepth = 1; nodeDepth <= maxDepth; nodeDepth += 1) {
    columnX.set(
      nodeDepth,
      (columnX.get(nodeDepth - 1) || 0) +
        (maxWidthByDepth.get(nodeDepth - 1) || 1) / 2 +
        horizontalGap +
        (maxWidthByDepth.get(nodeDepth) || 1) / 2,
    );
  }

  const rootChildren = tree.children.get(rootId) || [];
  const { right, left } = splitRootChildren(
    rootChildren,
    subtreeExtents,
    verticalGap,
    rightRatio,
  );
  const rawPositions = new Map<string, MindMapLayoutPoint>([
    [rootId, { x: 0, y: 0 }],
  ]);
  const sideByNode = new Map<string, MindMapLayoutSide>([[rootId, "root"]]);

  const placeSubtree = (
    seed: string,
    seedY: number,
    side: Exclude<MindMapLayoutSide, "root">,
  ) => {
    const stack: Array<[string, number]> = [[seed, seedY]];
    while (stack.length) {
      const current = stack.pop();
      if (!current) continue;
      const [nodeId, centerY] = current;
      const nodeDepth = tree.depth.get(nodeId) || 0;
      rawPositions.set(nodeId, {
        x: (side === "right" ? 1 : -1) * (columnX.get(nodeDepth) || 0),
        y: centerY,
      });
      sideByNode.set(nodeId, side);
      const childIds = tree.children.get(nodeId) || [];
      const childCenters = stackCenters(childIds, subtreeExtents, verticalGap);
      const descendants = childIds.map(
        (childId) =>
          [childId, centerY + (childCenters.get(childId) || 0)] as [
            string,
            number,
          ],
      );
      for (let index = descendants.length - 1; index >= 0; index -= 1) {
        stack.push(descendants[index]);
      }
    }
  };

  for (const [branchId, centerY] of stackCenters(
    right,
    subtreeExtents,
    verticalGap,
  )) {
    placeSubtree(branchId, centerY, "right");
  }
  for (const [branchId, centerY] of stackCenters(
    left,
    subtreeExtents,
    verticalGap,
  )) {
    placeSubtree(branchId, centerY, "left");
  }

  const rawBoxes = new Map<string, MindMapLayoutBox>();
  for (const [nodeId, point] of rawPositions) {
    const node = sizeById.get(nodeId);
    if (!node) continue;
    rawBoxes.set(nodeId, {
      left: point.x - node.width / 2,
      top: point.y - node.height / 2,
      right: point.x + node.width / 2,
      bottom: point.y + node.height / 2,
    });
  }
  const boxValues = [...rawBoxes.values()];
  const minX = Math.min(...boxValues.map((box) => box.left));
  const maxX = Math.max(...boxValues.map((box) => box.right));
  const minY = Math.min(...boxValues.map((box) => box.top));
  const maxY = Math.max(...boxValues.map((box) => box.bottom));
  const contentWidth = maxX - minX;
  const contentHeight = maxY - minY;
  const canvasWidth = Math.max(
    minimumCanvasWidth,
    Math.ceil(contentWidth + margin * 2),
  );
  const canvasHeight = Math.max(
    minimumCanvasHeight,
    Math.ceil(contentHeight + margin * 2 + titleSpace),
  );
  const offsetX = (canvasWidth - contentWidth) / 2 - minX;
  const offsetY =
    titleSpace + (canvasHeight - titleSpace - contentHeight) / 2 - minY;
  const positions = new Map(
    [...rawPositions].map(([nodeId, point]) => [
      nodeId,
      { x: point.x + offsetX, y: point.y + offsetY },
    ]),
  );
  const boxes = new Map(
    [...rawBoxes].map(([nodeId, box]) => [
      nodeId,
      {
        left: box.left + offsetX,
        top: box.top + offsetY,
        right: box.right + offsetX,
        bottom: box.bottom + offsetY,
      },
    ]),
  );
  return {
    positions,
    boxes,
    sideByNode,
    rootChildrenRight: right,
    rootChildrenLeft: left,
    subtreeExtents,
    canvasWidth,
    canvasHeight,
  };
};

export const findMindMapSpacingViolations = (
  layout: MindMapLayoutResult,
  minimumGap = 24,
) => {
  const nodeIds = [...layout.positions.keys()];
  const violations: Array<[string, string]> = [];
  for (let leftIndex = 0; leftIndex < nodeIds.length; leftIndex += 1) {
    const leftId = nodeIds[leftIndex];
    const leftBox = layout.boxes.get(leftId);
    if (!leftBox) continue;
    for (const rightId of nodeIds.slice(leftIndex + 1)) {
      const rightBox = layout.boxes.get(rightId);
      if (!rightBox) continue;
      const horizontalGap = Math.max(
        rightBox.left - leftBox.right,
        leftBox.left - rightBox.right,
        0,
      );
      const verticalGap = Math.max(
        rightBox.top - leftBox.bottom,
        leftBox.top - rightBox.bottom,
        0,
      );
      if (horizontalGap < minimumGap && verticalGap < minimumGap) {
        violations.push([leftId, rightId]);
      }
    }
  }
  return violations;
};

export const collapseMindMapToBudget = ({
  nodeIds,
  edges,
  rootId,
  maxVisible = 120,
}: {
  nodeIds: string[];
  edges: MindMapLayoutEdge[];
  rootId: string;
  maxVisible?: number;
}): MindMapVisibilityResult => {
  if (maxVisible < 1) throw new Error("maxVisible 必须至少为 1");
  const tree = buildOrderedTree(nodeIds, edges, rootId);
  const visible = new Set<string>([rootId]);
  const pending = [rootId];
  let cursor = 0;
  while (cursor < pending.length && visible.size < maxVisible) {
    const parentId = pending[cursor];
    cursor += 1;
    for (const childId of tree.children.get(parentId) || []) {
      if (visible.size >= maxVisible) break;
      visible.add(childId);
      pending.push(childId);
    }
  }

  const hiddenCounts = new Map<string, number>();
  for (const nodeId of tree.nodeIds) {
    if (visible.has(nodeId)) continue;
    let ancestorId = tree.parent.get(nodeId) || rootId;
    while (!visible.has(ancestorId)) {
      ancestorId = tree.parent.get(ancestorId) || rootId;
    }
    hiddenCounts.set(ancestorId, (hiddenCounts.get(ancestorId) || 0) + 1);
  }
  return {
    visibleNodeIds: tree.nodeIds.filter((nodeId) => visible.has(nodeId)),
    hiddenCounts,
  };
};

export const wrapMindMapLabel = (
  value: string,
  unitsPerLine: number,
  maxLines: number,
) => {
  const lines: string[] = [];
  let current = "";
  let currentUnits = 0;
  const characters = Array.from(value.trim());
  let consumed = 0;
  for (const character of characters) {
    const units = /^[\x00-\x7F]$/.test(character) ? 0.55 : 1;
    if (current && currentUnits + units > unitsPerLine) {
      lines.push(current);
      current = "";
      currentUnits = 0;
      if (lines.length === maxLines) break;
    }
    current += character;
    currentUnits += units;
    consumed += 1;
  }
  if (current && lines.length < maxLines) lines.push(current);
  if (consumed < characters.length && lines.length > 0) {
    const last = lines.length - 1;
    lines[last] = `${lines[last].slice(0, -1)}…`;
  }
  return lines.join("\n") || value;
};

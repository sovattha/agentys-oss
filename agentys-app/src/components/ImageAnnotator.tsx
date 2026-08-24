/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { CloseIcon } from './icons/ActionIcons';
import './ImageAnnotator.css';

const COLORS = ['#000000', '#ffffff', '#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6'];
const SIZES = [2, 4, 8, 14];

type Tool =
  | 'brush'
  | 'highlighter'
  | 'line'
  | 'arrow'
  | 'rect'
  | 'ellipse'
  | 'text'
  | 'number'
  | 'blur'
  | 'eraser'
  | 'crop';

type Point = { x: number; y: number };

type Shape =
  | { id: string; type: 'brush'; points: Point[]; color: string; width: number }
  | { id: string; type: 'highlighter'; points: Point[]; color: string; width: number }
  | { id: string; type: 'line'; x1: number; y1: number; x2: number; y2: number; color: string; width: number }
  | { id: string; type: 'arrow'; x1: number; y1: number; x2: number; y2: number; color: string; width: number }
  | { id: string; type: 'rect'; x: number; y: number; w: number; h: number; color: string; width: number }
  | { id: string; type: 'ellipse'; x: number; y: number; w: number; h: number; color: string; width: number }
  | { id: string; type: 'text'; text: string; x: number; y: number; color: string; size: number }
  | { id: string; type: 'number'; n: number; x: number; y: number; color: string; radius?: number }
  | { id: string; type: 'blur'; x: number; y: number; w: number; h: number };

interface ImageAnnotatorProps {
  src: string;
  onSave: (dataUrl: string) => void;
  onCancel: () => void;
}

const uid = () => Math.random().toString(36).slice(2, 10);

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return distance(p, a);
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return distance(p, { x: a.x + t * dx, y: a.y + t * dy });
}

function getContrastColor(bg: string): string {
  if (!bg.startsWith('#') || bg.length < 7) return '#ffffff';
  const r = parseInt(bg.slice(1, 3), 16);
  const g = parseInt(bg.slice(3, 5), 16);
  const b = parseInt(bg.slice(5, 7), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? '#111827' : '#ffffff';
}

function textSizeFor(strokeSize: number): number {
  return Math.max(18, Math.round(14 + strokeSize * 3));
}

function numberRadiusFor(strokeSize: number): number {
  return Math.max(9, Math.round(8 + strokeSize));
}

function drawBlurRegion(
  ctx: CanvasRenderingContext2D,
  source: HTMLCanvasElement,
  shape: { x: number; y: number; w: number; h: number }
) {
  const w = Math.max(1, Math.floor(shape.w));
  const h = Math.max(1, Math.floor(shape.h));
  if (w < 2 || h < 2) return;
  const pixel = 10;
  const small = document.createElement('canvas');
  small.width = Math.max(1, Math.floor(w / pixel));
  small.height = Math.max(1, Math.floor(h / pixel));
  const sctx = small.getContext('2d');
  if (!sctx) return;
  sctx.imageSmoothingEnabled = true;
  sctx.drawImage(source, shape.x, shape.y, w, h, 0, 0, small.width, small.height);
  const prevSmoothing = ctx.imageSmoothingEnabled;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(small, 0, 0, small.width, small.height, shape.x, shape.y, w, h);
  ctx.imageSmoothingEnabled = prevSmoothing;
}

function drawShape(ctx: CanvasRenderingContext2D, target: HTMLCanvasElement, shape: Shape) {
  ctx.save();
  switch (shape.type) {
    case 'brush':
    case 'highlighter': {
      const pts = shape.points;
      if (pts.length === 0) break;
      ctx.strokeStyle = shape.color;
      ctx.fillStyle = shape.color;
      ctx.lineWidth = shape.width;
      ctx.lineCap = shape.type === 'highlighter' ? 'butt' : 'round';
      ctx.lineJoin = 'round';
      if (shape.type === 'highlighter') ctx.globalAlpha = 0.35;
      if (pts.length === 1) {
        ctx.beginPath();
        ctx.arc(pts[0].x, pts[0].y, shape.width / 2, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
        ctx.stroke();
      }
      break;
    }
    case 'line': {
      ctx.strokeStyle = shape.color;
      ctx.lineWidth = shape.width;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(shape.x1, shape.y1);
      ctx.lineTo(shape.x2, shape.y2);
      ctx.stroke();
      break;
    }
    case 'arrow': {
      const { x1, y1, x2, y2, color, width } = shape;
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const headLen = Math.max(14, width * 3.5);
      const headAngle = Math.PI / 6;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      const shaftX = x2 - Math.cos(angle) * headLen * 0.7;
      const shaftY = y2 - Math.sin(angle) * headLen * 0.7;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(shaftX, shaftY);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - Math.cos(angle - headAngle) * headLen, y2 - Math.sin(angle - headAngle) * headLen);
      ctx.lineTo(x2 - Math.cos(angle + headAngle) * headLen, y2 - Math.sin(angle + headAngle) * headLen);
      ctx.closePath();
      ctx.fill();
      break;
    }
    case 'rect': {
      ctx.strokeStyle = shape.color;
      ctx.lineWidth = shape.width;
      ctx.lineJoin = 'round';
      ctx.strokeRect(shape.x, shape.y, shape.w, shape.h);
      break;
    }
    case 'ellipse': {
      if (shape.w < 1 || shape.h < 1) break;
      ctx.strokeStyle = shape.color;
      ctx.lineWidth = shape.width;
      ctx.beginPath();
      ctx.ellipse(shape.x + shape.w / 2, shape.y + shape.h / 2, shape.w / 2, shape.h / 2, 0, 0, Math.PI * 2);
      ctx.stroke();
      break;
    }
    case 'text': {
      ctx.font = `600 ${shape.size}px system-ui, -apple-system, Segoe UI, sans-serif`;
      ctx.fillStyle = shape.color;
      ctx.textBaseline = 'top';
      ctx.shadowColor = 'rgba(0,0,0,0.35)';
      ctx.shadowBlur = 3;
      ctx.fillText(shape.text, shape.x, shape.y);
      break;
    }
    case 'number': {
      const radius = shape.radius ?? 16;
      ctx.beginPath();
      ctx.arc(shape.x, shape.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = shape.color;
      ctx.shadowColor = 'rgba(0,0,0,0.28)';
      ctx.shadowBlur = Math.max(2, radius * 0.25);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = 'rgba(255,255,255,0.95)';
      ctx.lineWidth = Math.max(1, radius * 0.125);
      ctx.stroke();
      ctx.font = `bold ${Math.round(radius * 0.94)}px system-ui, -apple-system, sans-serif`;
      ctx.fillStyle = getContrastColor(shape.color);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(shape.n), shape.x, shape.y + radius * 0.06);
      break;
    }
    case 'blur': {
      drawBlurRegion(ctx, target, shape);
      break;
    }
  }
  ctx.restore();
}

function renderShapes(ctx: CanvasRenderingContext2D, target: HTMLCanvasElement, shapes: Shape[]) {
  for (const s of shapes) drawShape(ctx, target, s);
}

function scaleShape(shape: Shape, s: number): Shape {
  if (s === 1) return shape;
  switch (shape.type) {
    case 'brush':
    case 'highlighter':
      return {
        ...shape,
        points: shape.points.map((p) => ({ x: p.x * s, y: p.y * s })),
        width: shape.width * s,
      };
    case 'line':
    case 'arrow':
      return {
        ...shape,
        x1: shape.x1 * s,
        y1: shape.y1 * s,
        x2: shape.x2 * s,
        y2: shape.y2 * s,
        width: shape.width * s,
      };
    case 'rect':
    case 'ellipse':
      return {
        ...shape,
        x: shape.x * s,
        y: shape.y * s,
        w: shape.w * s,
        h: shape.h * s,
        width: shape.width * s,
      };
    case 'text':
      return { ...shape, x: shape.x * s, y: shape.y * s, size: shape.size * s };
    case 'number':
      return { ...shape, x: shape.x * s, y: shape.y * s, radius: (shape.radius ?? 16) * s };
    case 'blur':
      return { ...shape, x: shape.x * s, y: shape.y * s, w: shape.w * s, h: shape.h * s };
  }
}

function applyShiftConstraint(a: Point, b: Point, shiftHeld: boolean): Point {
  if (!shiftHeld) return b;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const angle = Math.atan2(dy, dx);
  const snap = Math.round(angle / (Math.PI / 4)) * (Math.PI / 4);
  const len = Math.hypot(dx, dy);
  return { x: a.x + Math.cos(snap) * len, y: a.y + Math.sin(snap) * len };
}

function applyShiftSquare(a: Point, b: Point, shiftHeld: boolean): Point {
  if (!shiftHeld) return b;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const side = Math.max(Math.abs(dx), Math.abs(dy));
  return { x: a.x + Math.sign(dx || 1) * side, y: a.y + Math.sign(dy || 1) * side };
}

function hitTest(shape: Shape, p: Point): boolean {
  const slop = 10;
  switch (shape.type) {
    case 'brush':
    case 'highlighter': {
      const tol = shape.width / 2 + slop;
      for (let i = 0; i < shape.points.length; i++) {
        if (i === 0) {
          if (distance(p, shape.points[0]) < tol) return true;
          continue;
        }
        if (distanceToSegment(p, shape.points[i - 1], shape.points[i]) < tol) return true;
      }
      return false;
    }
    case 'line':
    case 'arrow':
      return (
        distanceToSegment(p, { x: shape.x1, y: shape.y1 }, { x: shape.x2, y: shape.y2 }) <
        shape.width / 2 + slop
      );
    case 'rect': {
      const inOuter =
        p.x >= shape.x - slop &&
        p.x <= shape.x + shape.w + slop &&
        p.y >= shape.y - slop &&
        p.y <= shape.y + shape.h + slop;
      const inInner =
        p.x > shape.x + slop &&
        p.x < shape.x + shape.w - slop &&
        p.y > shape.y + slop &&
        p.y < shape.y + shape.h - slop;
      return inOuter && !inInner;
    }
    case 'ellipse': {
      const cx = shape.x + shape.w / 2;
      const cy = shape.y + shape.h / 2;
      const a = shape.w / 2;
      const b = shape.h / 2;
      if (a < 1 || b < 1) return false;
      const d = ((p.x - cx) / a) ** 2 + ((p.y - cy) / b) ** 2;
      return d >= 0.78 && d <= 1.22;
    }
    case 'text': {
      const tw = shape.text.length * shape.size * 0.58;
      const th = shape.size * 1.2;
      return (
        p.x >= shape.x - slop &&
        p.x <= shape.x + tw + slop &&
        p.y >= shape.y - slop &&
        p.y <= shape.y + th + slop
      );
    }
    case 'number':
      return distance(p, { x: shape.x, y: shape.y }) < 18;
    case 'blur':
      return (
        p.x >= shape.x && p.x <= shape.x + shape.w && p.y >= shape.y && p.y <= shape.y + shape.h
      );
  }
}

function cursorForTool(tool: Tool): string {
  switch (tool) {
    case 'text':
      return 'text';
    case 'eraser':
      return 'cell';
    default:
      return 'crosshair';
  }
}

export function ImageAnnotator({ src, onSave, onCancel }: ImageAnnotatorProps) {
  const { t } = useTranslation('compose');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const textInputRef = useRef<HTMLInputElement>(null);
  const [currentSrc, setCurrentSrc] = useState(src);
  const [tool, setTool] = useState<Tool>('brush');
  const [color, setColor] = useState('#ef4444');
  const [size, setSize] = useState(4);
  const [shapes, setShapes] = useState<Shape[]>([]);
  const [undoneShapes, setUndoneShapes] = useState<Shape[]>([]);
  const [canvasSize, setCanvasSize] = useState<{ w: number; h: number } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [numberCounter, setNumberCounter] = useState(1);
  const [pendingText, setPendingText] = useState<{ x: number; y: number; cx: number; cy: number } | null>(
    null
  );
  const [pendingTextValue, setPendingTextValue] = useState('');
  const [cropRect, setCropRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  const drawingRef = useRef(false);
  const startRef = useRef<Point | null>(null);
  const currentPointsRef = useRef<Point[]>([]);
  const currentEndRef = useRef<Point | null>(null);
  const shiftRef = useRef(false);

  // Append a shape from a user action and invalidate the redo stack: any new
  // edit after an undo branches the history, dropping the redo tail.
  const pushShape = useCallback((shape: Shape) => {
    setShapes((prev) => [...prev, shape]);
    setUndoneShapes([]);
  }, []);

  useEffect(() => {
    const img = new window.Image();
    img.onload = () => {
      imgRef.current = img;
      const maxW = Math.min(window.innerWidth - 80, 1400);
      const maxH = Math.min(window.innerHeight - 280, 900);
      const ratio = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
      setCanvasSize({
        w: Math.round(img.naturalWidth * ratio),
        h: Math.round(img.naturalHeight * ratio),
      });
    };
    img.src = currentSrc;
  }, [currentSrc]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Shift') shiftRef.current = true;
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Shift') shiftRef.current = false;
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, []);

  useEffect(() => {
    overlayRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!pendingText) {
      overlayRef.current?.focus();
      return;
    }
    const id = requestAnimationFrame(() => {
      textInputRef.current?.focus();
      textInputRef.current?.select();
    });
    return () => cancelAnimationFrame(id);
  }, [pendingText]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 1800);
    return () => clearTimeout(id);
  }, [toast]);

  useEffect(() => {
    if (tool !== 'crop' && cropRect) setCropRect(null);
  }, [tool, cropRect]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !canvasSize) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvasSize.w, canvasSize.h);
    ctx.drawImage(img, 0, 0, canvasSize.w, canvasSize.h);
    renderShapes(ctx, canvas, shapes);

    if (drawingRef.current && startRef.current) {
      const s = startRef.current;
      if (tool === 'brush' || tool === 'highlighter') {
        const previewWidth = tool === 'highlighter' ? Math.max(size * 5, 20) : size;
        const preview: Shape = {
          id: '_',
          type: tool,
          points: currentPointsRef.current,
          color,
          width: previewWidth,
        };
        drawShape(ctx, canvas, preview);
      } else if ((tool === 'line' || tool === 'arrow') && currentEndRef.current) {
        const end = applyShiftConstraint(s, currentEndRef.current, shiftRef.current);
        const preview: Shape = {
          id: '_',
          type: tool,
          x1: s.x,
          y1: s.y,
          x2: end.x,
          y2: end.y,
          color,
          width: size,
        };
        drawShape(ctx, canvas, preview);
      } else if ((tool === 'rect' || tool === 'ellipse' || tool === 'blur') && currentEndRef.current) {
        const end =
          tool === 'rect' || tool === 'ellipse'
            ? applyShiftSquare(s, currentEndRef.current, shiftRef.current)
            : currentEndRef.current;
        const x = Math.min(s.x, end.x);
        const y = Math.min(s.y, end.y);
        const w = Math.abs(end.x - s.x);
        const h = Math.abs(end.y - s.y);
        if (tool === 'blur') {
          drawShape(ctx, canvas, { id: '_', type: 'blur', x, y, w, h });
        } else {
          drawShape(ctx, canvas, { id: '_', type: tool, x, y, w, h, color, width: size });
        }
      }
    }

    const showingCrop =
      cropRect || (drawingRef.current && tool === 'crop' && startRef.current && currentEndRef.current);
    if (showingCrop) {
      const r =
        cropRect ||
        (() => {
          const end = currentEndRef.current!;
          const s = startRef.current!;
          return {
            x: Math.min(s.x, end.x),
            y: Math.min(s.y, end.y),
            w: Math.abs(end.x - s.x),
            h: Math.abs(end.y - s.y),
          };
        })();
      ctx.save();
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.beginPath();
      ctx.rect(0, 0, canvasSize.w, canvasSize.h);
      ctx.rect(r.x, r.y, r.w, r.h);
      ctx.fill('evenodd');
      ctx.restore();

      ctx.save();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(r.x, r.y, r.w, r.h);
      ctx.setLineDash([]);
      const hs = 8;
      ctx.fillStyle = '#ffffff';
      const handles: [number, number][] = [
        [r.x, r.y],
        [r.x + r.w, r.y],
        [r.x, r.y + r.h],
        [r.x + r.w, r.y + r.h],
        [r.x + r.w / 2, r.y],
        [r.x + r.w / 2, r.y + r.h],
        [r.x, r.y + r.h / 2],
        [r.x + r.w, r.y + r.h / 2],
      ];
      handles.forEach(([hx, hy]) => {
        ctx.fillRect(hx - hs / 2, hy - hs / 2, hs, hs);
      });
      ctx.restore();
    }
  }, [canvasSize, shapes, tool, color, size, cropRect]);

  useEffect(() => {
    redraw();
  }, [redraw]);

  const flattenCanvas = useCallback(
    (mode: 'display' | 'natural' = 'natural'): HTMLCanvasElement | null => {
      const img = imgRef.current;
      if (!img || !canvasSize) return null;
      const useNatural = mode === 'natural' && img.naturalWidth > 0;
      const w = useNatural ? img.naturalWidth : canvasSize.w;
      const h = useNatural ? img.naturalHeight : canvasSize.h;
      const scale = useNatural ? img.naturalWidth / canvasSize.w : 1;
      const off = document.createElement('canvas');
      off.width = w;
      off.height = h;
      const ctx = off.getContext('2d');
      if (!ctx) return null;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(img, 0, 0, w, h);
      const scaled = scale === 1 ? shapes : shapes.map((s) => scaleShape(s, scale));
      renderShapes(ctx, off, scaled);
      return off;
    },
    [canvasSize, shapes]
  );

  const getPos = useCallback((e: React.MouseEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  }, []);

  const findShapeAt = useCallback(
    (p: Point): Shape | null => {
      for (let i = shapes.length - 1; i >= 0; i--) {
        if (hitTest(shapes[i], p)) return shapes[i];
      }
      return null;
    },
    [shapes]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (pendingText) return;
      e.preventDefault();
      e.stopPropagation();
      const pos = getPos(e);

      if (tool === 'eraser') {
        const hit = findShapeAt(pos);
        if (hit) {
          setShapes((prev) => prev.filter((s) => s.id !== hit.id));
          setUndoneShapes([]);
        }
        return;
      }

      if (tool === 'text') {
        const clientRect = canvasRef.current!.getBoundingClientRect();
        setPendingText({
          x: pos.x,
          y: pos.y,
          cx: e.clientX - clientRect.left,
          cy: e.clientY - clientRect.top,
        });
        setPendingTextValue('');
        return;
      }

      if (tool === 'number') {
        const shape: Shape = {
          id: uid(),
          type: 'number',
          n: numberCounter,
          x: pos.x,
          y: pos.y,
          color,
          radius: numberRadiusFor(size),
        };
        pushShape(shape);
        setNumberCounter((n) => n + 1);
        return;
      }

      if (tool === 'crop' && cropRect) {
        setCropRect(null);
      }

      drawingRef.current = true;
      startRef.current = pos;
      currentPointsRef.current = [pos];
      currentEndRef.current = pos;
      redraw();
    },
    [tool, getPos, pendingText, numberCounter, color, size, cropRect, redraw, findShapeAt, pushShape]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return;
      const pos = getPos(e);
      if (tool === 'brush' || tool === 'highlighter') {
        currentPointsRef.current.push(pos);
      } else {
        currentEndRef.current = pos;
      }
      redraw();
    },
    [tool, getPos, redraw]
  );

  const handleMouseUp = useCallback(() => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    const start = startRef.current;
    const end = currentEndRef.current;
    startRef.current = null;

    if ((tool === 'brush' || tool === 'highlighter') && currentPointsRef.current.length > 0) {
      const width = tool === 'highlighter' ? Math.max(size * 5, 20) : size;
      const shape: Shape = {
        id: uid(),
        type: tool,
        points: [...currentPointsRef.current],
        color,
        width,
      };
      pushShape(shape);
    } else if (start && end) {
      if (tool === 'line' || tool === 'arrow') {
        const e2 = applyShiftConstraint(start, end, shiftRef.current);
        if (distance(start, e2) > 3) {
          const shape: Shape = {
            id: uid(),
            type: tool,
            x1: start.x,
            y1: start.y,
            x2: e2.x,
            y2: e2.y,
            color,
            width: size,
          };
          pushShape(shape);
        }
      } else if (tool === 'rect' || tool === 'ellipse') {
        const e2 = applyShiftSquare(start, end, shiftRef.current);
        const x = Math.min(start.x, e2.x);
        const y = Math.min(start.y, e2.y);
        const w = Math.abs(e2.x - start.x);
        const h = Math.abs(e2.y - start.y);
        if (w > 3 && h > 3) {
          const shape: Shape = { id: uid(), type: tool, x, y, w, h, color, width: size };
          pushShape(shape);
        }
      } else if (tool === 'blur') {
        const x = Math.min(start.x, end.x);
        const y = Math.min(start.y, end.y);
        const w = Math.abs(end.x - start.x);
        const h = Math.abs(end.y - start.y);
        if (w > 5 && h > 5) {
          pushShape({ id: uid(), type: 'blur', x, y, w, h });
        }
      } else if (tool === 'crop') {
        const x = Math.min(start.x, end.x);
        const y = Math.min(start.y, end.y);
        const w = Math.abs(end.x - start.x);
        const h = Math.abs(end.y - start.y);
        if (w > 10 && h > 10) setCropRect({ x, y, w, h });
      }
    }
    currentPointsRef.current = [];
    currentEndRef.current = null;
  }, [tool, size, color, pushShape]);

  const handleUndo = useCallback(() => {
    if (shapes.length === 0) return;
    const last = shapes[shapes.length - 1];
    setShapes((prev) => prev.slice(0, -1));
    setUndoneShapes((prev) => [...prev, last]);
    if (last.type === 'number') setNumberCounter((n) => Math.max(1, n - 1));
  }, [shapes]);

  const handleRedo = useCallback(() => {
    if (undoneShapes.length === 0) return;
    const last = undoneShapes[undoneShapes.length - 1];
    setUndoneShapes((prev) => prev.slice(0, -1));
    setShapes((prev) => [...prev, last]);
    if (last.type === 'number') setNumberCounter((n) => n + 1);
  }, [undoneShapes]);

  const commitText = useCallback(() => {
    if (!pendingText) return;
    const value = pendingTextValue.trim();
    if (value) {
      const shape: Shape = {
        id: uid(),
        type: 'text',
        text: value,
        x: pendingText.x,
        y: pendingText.y,
        color,
        size: textSizeFor(size),
      };
      pushShape(shape);
    }
    setPendingText(null);
    setPendingTextValue('');
  }, [pendingText, pendingTextValue, color, size, pushShape]);

  const cancelText = useCallback(() => {
    setPendingText(null);
    setPendingTextValue('');
  }, []);

  const applyCrop = useCallback(() => {
    if (!cropRect || !imgRef.current || !canvasSize) return;
    const off = flattenCanvas('natural');
    if (!off) return;
    const scale = imgRef.current.naturalWidth / canvasSize.w;
    const r = cropRect;
    const nx = r.x * scale;
    const ny = r.y * scale;
    const nw = r.w * scale;
    const nh = r.h * scale;
    const final = document.createElement('canvas');
    final.width = Math.max(1, Math.round(nw));
    final.height = Math.max(1, Math.round(nh));
    const fctx = final.getContext('2d');
    if (!fctx) return;
    fctx.drawImage(off, nx, ny, nw, nh, 0, 0, final.width, final.height);
    setShapes([]);
    setUndoneShapes([]);
    setCropRect(null);
    setNumberCounter(1);
    setCurrentSrc(final.toDataURL('image/png'));
    setTool('brush');
  }, [cropRect, canvasSize, flattenCanvas]);

  const cancelCrop = useCallback(() => {
    setCropRect(null);
  }, []);

  const rotate = useCallback(() => {
    const off = flattenCanvas('natural');
    if (!off) return;
    const rotated = document.createElement('canvas');
    rotated.width = off.height;
    rotated.height = off.width;
    const rctx = rotated.getContext('2d');
    if (!rctx) return;
    rctx.imageSmoothingEnabled = true;
    rctx.imageSmoothingQuality = 'high';
    rctx.translate(rotated.width, 0);
    rctx.rotate(Math.PI / 2);
    rctx.drawImage(off, 0, 0);
    setShapes([]);
    setUndoneShapes([]);
    setCropRect(null);
    setNumberCounter(1);
    setCurrentSrc(rotated.toDataURL('image/png'));
  }, [flattenCanvas]);

  const copyToClipboard = useCallback(async () => {
    const off = flattenCanvas('natural');
    if (!off) return;
    try {
      const blob: Blob = await new Promise((resolve, reject) => {
        off.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png');
      });
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        'write' in navigator.clipboard &&
        typeof ClipboardItem !== 'undefined'
      ) {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        setToast(t('annotator_copied'));
      } else {
        setToast(t('annotator_copy_unsupported'));
      }
    } catch {
      setToast(t('annotator_copy_failed'));
    }
  }, [flattenCanvas, t]);

  const handleSave = useCallback(() => {
    const off = flattenCanvas('natural');
    if (!off) return;
    onSave(off.toDataURL('image/png'));
  }, [flattenCanvas, onSave]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (pendingText) return;
      if (e.key === 'Escape') {
        if (cropRect) {
          cancelCrop();
          return;
        }
        onCancel();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        handleRedo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        handleUndo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        handleRedo();
        return;
      }
      if (
        (e.ctrlKey || e.metaKey) &&
        e.key.toLowerCase() === 'c' &&
        !window.getSelection()?.toString()
      ) {
        e.preventDefault();
        copyToClipboard();
        return;
      }
      if (cropRect && e.key === 'Enter') {
        applyCrop();
        return;
      }
      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        const map: Record<string, Tool> = {
          b: 'brush',
          h: 'highlighter',
          l: 'line',
          a: 'arrow',
          r: 'rect',
          o: 'ellipse',
          t: 'text',
          n: 'number',
          x: 'blur',
          e: 'eraser',
          c: 'crop',
        };
        const k = e.key.toLowerCase();
        if (map[k]) {
          setTool(map[k]);
          return;
        }
      }
    },
    [pendingText, cropRect, onCancel, handleUndo, handleRedo, copyToClipboard, applyCrop, cancelCrop]
  );

  const tools = useMemo<{ id: Tool; label: string; shortcut: string; icon: JSX.Element }[]>(
    () => [
      {
        id: 'brush',
        label: t('annotator_brush'),
        shortcut: 'B',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18.37 2.63 14 7l-1.59-1.59a2 2 0 0 0-2.82 0L8 7l9 9 1.59-1.59a2 2 0 0 0 0-2.82L17 10l4.37-4.37a2.12 2.12 0 1 0-3-3Z" />
            <path d="M9 8c-2 3-4 3.5-7 4l8 10c2-1 6-5 6-7" />
            <path d="M14.5 17.5 4.5 15" />
          </svg>
        ),
      },
      {
        id: 'highlighter',
        label: t('annotator_highlighter'),
        shortcut: 'H',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m9 11-6 6v3h9l3-3" />
            <path d="M22 12 14 4l-6 6 8 8 6-6z" />
          </svg>
        ),
      },
      {
        id: 'line',
        label: t('annotator_line'),
        shortcut: 'L',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="5" y1="19" x2="19" y2="5" />
          </svg>
        ),
      },
      {
        id: 'arrow',
        label: t('annotator_arrow'),
        shortcut: 'A',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="19" x2="17" y2="7" />
            <polyline points="10 6 18 6 18 14" />
          </svg>
        ),
      },
      {
        id: 'rect',
        label: t('annotator_rect'),
        shortcut: 'R',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="4" y="5" width="16" height="14" rx="1.5" />
          </svg>
        ),
      },
      {
        id: 'ellipse',
        label: t('annotator_ellipse'),
        shortcut: 'O',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <ellipse cx="12" cy="12" rx="9" ry="7" />
          </svg>
        ),
      },
      {
        id: 'text',
        label: t('annotator_text'),
        shortcut: 'T',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4 7 4 4 20 4 20 7" />
            <line x1="9" y1="20" x2="15" y2="20" />
            <line x1="12" y1="4" x2="12" y2="20" />
          </svg>
        ),
      },
      {
        id: 'number',
        label: t('annotator_number'),
        shortcut: 'N',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <text x="12" y="16" textAnchor="middle" fontSize="10" fontWeight="700" fill="currentColor" stroke="none">
              1
            </text>
          </svg>
        ),
      },
      {
        id: 'blur',
        label: t('annotator_blur'),
        shortcut: 'X',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="none">
            <circle cx="6" cy="6" r="1.4" />
            <circle cx="12" cy="6" r="1.4" />
            <circle cx="18" cy="6" r="1.4" />
            <circle cx="6" cy="12" r="1.4" />
            <circle cx="12" cy="12" r="1.4" />
            <circle cx="18" cy="12" r="1.4" />
            <circle cx="6" cy="18" r="1.4" />
            <circle cx="12" cy="18" r="1.4" />
            <circle cx="18" cy="18" r="1.4" />
          </svg>
        ),
      },
      {
        id: 'eraser',
        label: t('annotator_eraser'),
        shortcut: 'E',
        icon: (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 20H8L3 15a2 2 0 0 1 0-2.83L12.17 3a2 2 0 0 1 2.83 0l6 6a2 2 0 0 1 0 2.83L14 18" />
            <line x1="18" y1="13" x2="9" y2="4" />
          </svg>
        ),
      },
    ],
    [t]
  );

  const textInputStyle = useMemo<React.CSSProperties | null>(() => {
    if (!pendingText || !canvasRef.current) return null;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const scale = rect.width / canvas.width;
    return {
      left: pendingText.cx,
      top: pendingText.cy,
      color,
      fontSize: textSizeFor(size) * scale,
      minWidth: 40,
    };
  }, [pendingText, color, size]);

  return createPortal(
    <div
      className="ia-overlay"
      onKeyDown={handleKeyDown}
      tabIndex={-1}
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label={t('annotator_title')}
    >
      <div className="ia-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ia-header">
          <span className="ia-title">{t('annotator_title')}</span>
          <button
            type="button"
            className="ia-close"
            onClick={onCancel}
            aria-label={t('cancel')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="ia-toolbar">
          <div className="ia-tool-group" role="toolbar" aria-label={t('annotator_tools_label')}>
            {tools.map(({ id, label, icon, shortcut }) => (
              <button
                key={id}
                type="button"
                className={`ia-tool-btn${tool === id ? ' active' : ''}`}
                onClick={() => setTool(id)}
                title={`${label} (${shortcut})`}
                aria-label={label}
                aria-pressed={tool === id}
              >
                {icon}
              </button>
            ))}
          </div>

          <span className="ia-separator" />

          <div className="ia-tool-group">
            <button
              type="button"
              className={`ia-tool-btn${tool === 'crop' ? ' active' : ''}`}
              onClick={() => setTool('crop')}
              title={`${t('annotator_crop')} (C)`}
              aria-label={t('annotator_crop')}
              aria-pressed={tool === 'crop'}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 2v14a2 2 0 0 0 2 2h14" />
                <path d="M18 22V8a2 2 0 0 0-2-2H2" />
              </svg>
            </button>
            <button
              type="button"
              className="ia-tool-btn"
              onClick={rotate}
              title={t('annotator_rotate')}
              aria-label={t('annotator_rotate')}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="21 2 21 8 15 8" />
                <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
              </svg>
            </button>
          </div>

          <span className="ia-separator" />

          <div className="ia-colors">
            {COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className={`ia-color-swatch${color === c ? ' active' : ''}`}
                style={{ background: c, border: c === '#ffffff' ? '1px solid #d1d5db' : undefined }}
                onClick={() => setColor(c)}
                aria-label={c}
              />
            ))}
          </div>

          <span className="ia-separator" />

          <div className="ia-sizes">
            {SIZES.map((s) => (
              <button
                key={s}
                type="button"
                className={`ia-size-btn${size === s ? ' active' : ''}`}
                onClick={() => setSize(s)}
                title={`${s}px`}
                aria-label={`${s}px`}
              >
                <span className="ia-size-dot" style={{ width: s + 4, height: s + 4 }} />
              </button>
            ))}
          </div>

          <span className="ia-separator" />

          <div className="ia-tool-group">
            <button
              type="button"
              className="ia-tool-btn"
              onClick={handleUndo}
              disabled={shapes.length === 0}
              title={`${t('annotator_undo')} (Ctrl+Z)`}
              aria-label={t('annotator_undo')}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7v6h6" />
                <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
              </svg>
            </button>
            <button
              type="button"
              className="ia-tool-btn"
              onClick={handleRedo}
              disabled={undoneShapes.length === 0}
              title={`${t('annotator_redo')} (Ctrl+Shift+Z)`}
              aria-label={t('annotator_redo')}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 7v6h-6" />
                <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13" />
              </svg>
            </button>
            <button
              type="button"
              className="ia-tool-btn"
              onClick={copyToClipboard}
              title={`${t('annotator_copy')} (Ctrl+C)`}
              aria-label={t('annotator_copy')}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
            </button>
          </div>
        </div>

        {cropRect && (
          <div className="ia-crop-bar">
            <span className="ia-crop-hint">
              {t('annotator_crop_hint')}{' '}
              <span className="ia-crop-dims">
                {Math.round(cropRect.w)} × {Math.round(cropRect.h)}
              </span>
            </span>
            <button type="button" className="ia-btn-ghost" onClick={cancelCrop}>
              {t('cancel')}
            </button>
            <button type="button" className="ia-btn-primary" onClick={applyCrop}>
              {t('annotator_crop_apply')}
            </button>
          </div>
        )}

        <div className="ia-canvas-wrapper" ref={wrapperRef}>
          {canvasSize && (
            <div className="ia-canvas-stage">
              <canvas
                ref={canvasRef}
                width={canvasSize.w}
                height={canvasSize.h}
                className="ia-draw-canvas"
                style={{ cursor: cursorForTool(tool) }}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
              />
              {pendingText && textInputStyle && (
                <input
                  ref={textInputRef}
                  type="text"
                  className="ia-text-input"
                  style={textInputStyle}
                  value={pendingTextValue}
                  onChange={(e) => setPendingTextValue(e.target.value)}
                  onMouseDown={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      e.stopPropagation();
                      commitText();
                    } else if (e.key === 'Escape') {
                      e.preventDefault();
                      e.stopPropagation();
                      cancelText();
                    } else {
                      e.stopPropagation();
                    }
                  }}
                  onBlur={commitText}
                  placeholder={t('annotator_text_placeholder')}
                />
              )}
            </div>
          )}
        </div>

        {toast && <div className="ia-toast">{toast}</div>}

        <div className="ia-footer">
          <button type="button" className="ia-btn-cancel" onClick={onCancel}>
            {t('cancel')}
          </button>
          <button type="button" className="ia-btn-save" onClick={handleSave}>
            {t('annotator_save')}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

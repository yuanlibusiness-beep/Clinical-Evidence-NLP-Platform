"use client";

/**
 * Segmented control with a sliding selection pill.
 *
 * The pill is one absolutely-positioned element that moves to the measured box
 * of the active button, so labels of any width work and the motion is a single
 * transform-like transition (left + width on the calm curve) rather than a
 * background swap. Buttons are real tabs for keyboard and screen readers.
 */

import { useCallback, useLayoutEffect, useRef, useState } from "react";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  className = "",
  size = "md",
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  className?: string;
  size?: "md" | "lg";
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const buttonRefs = useRef<Map<T, HTMLButtonElement>>(new Map());
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);

  const measure = useCallback(() => {
    const button = buttonRefs.current.get(value);
    if (!button) return;
    setPill({ left: button.offsetLeft, width: button.offsetWidth });
  }, [value]);

  useLayoutEffect(() => {
    measure();
    const track = trackRef.current;
    if (!track || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    return () => observer.disconnect();
  }, [measure]);

  const height = size === "lg" ? "h-[38px]" : "h-9";

  return (
    <div
      ref={trackRef}
      role="tablist"
      aria-label={label}
      className={`relative inline-flex rounded-xl bg-[#ECEFF5] p-1 shadow-[inset_0_0_0_1px_#E0E4EC] ${className}`}
    >
      {pill && (
        <span
          aria-hidden="true"
          className="absolute bottom-1 top-1 rounded-[9px] bg-accent shadow-pill transition-[left,width] duration-500 ease-calm"
          style={{ left: pill.left, width: pill.width }}
        />
      )}
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              if (node) buttonRefs.current.set(option.value, node);
              else buttonRefs.current.delete(option.value);
            }}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={`relative ${height} flex-1 whitespace-nowrap rounded-[9px] px-4 text-[13px] font-semibold transition-colors duration-300 ${
              active ? "text-white" : "text-[#3F4756] hover:text-ink-900"
            } ${pill ? "" : active ? "bg-accent" : ""}`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

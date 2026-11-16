/** Stroke icons drawn for this UI; `currentColor` so they follow text colour. */

type IconProps = { size?: number; className?: string };

function svgProps(size: number, className?: string) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    className,
  };
}

export function CheckIcon({ size = 14, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)} strokeWidth={2}>
      <path d="M3.5 8.5l2.8 2.8L12.5 5" />
    </svg>
  );
}

export function DownloadIcon({ size = 16, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M8 2v8m0 0L5 7m3 3l3-3M3 12.5h10" />
    </svg>
  );
}

export function SearchIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="7" cy="7" r="4.6" />
      <path d="M10.6 10.6L14 14" />
    </svg>
  );
}

export function UploadIcon({ size = 28, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)} strokeWidth={1.4}>
      <path d="M4.5 2.5h4.5l3.5 3.5v7.2a.6.6 0 0 1-.6.6H4.5a.6.6 0 0 1-.6-.6V3.1a.6.6 0 0 1 .6-.6z" />
      <path d="M9 2.5V6h3.5M8.2 11.8V8.2m0 0L6.8 9.6m1.4-1.4l1.4 1.4" />
    </svg>
  );
}

export function AlertIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="8" cy="8" r="6.3" />
      <path d="M8 5v3.6M8 10.9v.1" />
    </svg>
  );
}

export function ChevronIcon({ size = 14, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M4.5 6.5L8 10l3.5-3.5" />
    </svg>
  );
}

export function ArrowLeftIcon({ size = 14, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M12.5 8h-9m0 0L7 4.5M3.5 8L7 11.5" />
    </svg>
  );
}

export function ArrowRightIcon({ size = 14, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M3.5 8h9m0 0L9 4.5M12.5 8L9 11.5" />
    </svg>
  );
}

export function TrashIcon({ size = 15, className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.3a.8.8 0 0 0 .8.7h4.2a.8.8 0 0 0 .8-.7l.6-8.3" />
    </svg>
  );
}

export function LogoMark() {
  return (
    <span
      aria-hidden="true"
      className="flex h-[30px] w-[30px] items-center justify-center rounded-[10px] bg-ink-900 text-white"
    >
      <CheckIcon size={16} />
    </span>
  );
}

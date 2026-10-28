// One icon family: 24px grid, 1.5px round strokes, currentColor. Decorative by default.
const PATHS = {
  home: "M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z",
  progress: "M4 20h16M7 16.5V12M11 16.5V8M15 16.5v-6M19 16.5V5",
  plus: "M12 5v14M5 12h14",
  routine: "M8 3.5h8M9 3.5v3.2c0 .5-.3 1-.7 1.3A3.5 3.5 0 0 0 7 10.8V19a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 17 19v-8.2a3.5 3.5 0 0 0-1.3-2.8c-.4-.3-.7-.8-.7-1.3V3.5M7 13.5h10",
  learn: "M12 6.5c-1.8-1.3-4.3-2-7.5-2v13c3.2 0 5.7.7 7.5 2 1.8-1.3 4.3-2 7.5-2v-13c-3.2 0-5.7.7-7.5 2zM12 6.5v13",
  back: "M14.5 5.5 8 12l6.5 6.5",
  chevron: "M9.5 5.5 16 12l-6.5 6.5",
  close: "M6 6l12 12M18 6 6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4",
  frame: "M4 8.5V5a1 1 0 0 1 1-1h3.5M15.5 4H19a1 1 0 0 1 1 1v3.5M20 15.5V19a1 1 0 0 1-1 1h-3.5M8.5 20H5a1 1 0 0 1-1-1v-3.5M12 7.5c-2.2 0-3.5 1.9-3.5 4.3 0 2.5 1.6 4.7 3.5 4.7s3.5-2.2 3.5-4.7c0-2.4-1.3-4.3-3.5-4.3z",
  pose: "M12 3.5c-3.3 0-6 2.7-6 6.2 0 4.5 3.8 9.3 6 10.8 2.2-1.5 6-6.3 6-10.8 0-3.5-2.7-6.2-6-6.2zM12 3.5v17",
  clock: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 7.5V12l3 2",
  phone: "M8 2.5h8A1.5 1.5 0 0 1 17.5 4v16a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20V4A1.5 1.5 0 0 1 8 2.5zM10.5 18.5h3",
  layers: "M12 4 3.5 8.5 12 13l8.5-4.5zM3.5 12.5 12 17l8.5-4.5M3.5 16.5 12 21l8.5-4.5",
  lock: "M7 10.5V8a5 5 0 0 1 10 0v2.5M5.5 10.5h13a1 1 0 0 1 1 1V20a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1v-8.5a1 1 0 0 1 1-1z",
  bell: "M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2H5zM10 20.5a2 2 0 0 0 4 0",
  file: "M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8zM14 3.5V8h4.5M9 12.5h6M9 16h6",
  share: "M12 15V3.5M8 7.5l4-4 4 4M6.5 11H5.5a1 1 0 0 0-1 1v7.5a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1V12a1 1 0 0 0-1-1h-1",
  search: "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.5 15.5 20 20",
  compare: "M8 4v16M16 4v16M4 8h8M12 16h8",
  trash: "M4.5 6.5h15M9.5 6.5V4.5h5v2M6.5 6.5l.8 12.6a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12.6",
  wave: "M3 13c2-5 4-5 6 0s4 5 6 0 4-5 6 0",
  alert: "M12 4 2.8 19.5h18.4zM12 10v4.5M12 17.2v.3",
  dot: "M12 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z",
  arrow: "M5 12h14M13.5 6.5 19 12l-5.5 5.5",
  history: "M4 12a8 8 0 1 0 2.3-5.6M4 4.5v3.5h3.5M12 8v4l2.5 2",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 22, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

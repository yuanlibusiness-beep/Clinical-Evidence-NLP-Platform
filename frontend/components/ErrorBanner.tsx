"use client";

/**
 * The backend's `detail` string is almost always actionable ("Index incomplete:
 * 3/8 chunks embedded"), so it is shown verbatim rather than replaced with a
 * generic message.
 */
export function ErrorBanner({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex animate-fade-in items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3"
    >
      <span aria-hidden className="mt-0.5 text-red-500">
        ●
      </span>
      <p className="flex-1 text-sm leading-relaxed text-red-800">{message}</p>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-xs text-red-600 hover:underline"
          aria-label="Dismiss"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

"use client";

/**
 * The backend's `detail` string is almost always actionable ("Index incomplete:
 * 3/8 chunks embedded"), so it is shown verbatim rather than replaced with a
 * generic message.
 */

import { AlertIcon } from "@/components/Icons";

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
      className="flex animate-rise items-start gap-3 rounded-2xl bg-[#FEF2F2] px-5 py-4 shadow-[inset_0_0_0_1px_#FBD5D5]"
    >
      <AlertIcon className="mt-0.5 shrink-0 text-[#B42318]" />
      <p className="flex-1 text-[13.5px] leading-relaxed text-[#7A1D14]">{message}</p>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="rounded-lg px-2 py-1 text-xs font-semibold text-[#B42318] transition-colors hover:bg-[#FDE3E3]"
          aria-label="Dismiss error"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

/** The amber "read this before trusting the numbers" box. */
export function NoticeBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex animate-rise items-start gap-3.5 rounded-[18px] bg-notice px-5 py-4 shadow-[inset_0_0_0_1px_#F6DFBC]">
      <AlertIcon size={20} className="mt-px shrink-0 text-notice-icon" />
      <div className="text-[13.5px] leading-relaxed text-notice-ink">{children}</div>
    </div>
  );
}

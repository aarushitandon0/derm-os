// A small, standards-conforming .ics file for a trial's check-in dates (RFC 5545).
import { addDays, localISODate } from "./copy";

const esc = (s: string) =>
  s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

// Lines longer than 75 octets are folded with CRLF + space.
function fold(line: string): string {
  const bytes = new TextEncoder().encode(line);
  if (bytes.length <= 75) return line;
  const out: string[] = [];
  let cur = "";
  let len = 0;
  for (const ch of line) {
    const n = new TextEncoder().encode(ch).length;
    if (len + n > (out.length ? 74 : 75)) {
      out.push(cur);
      cur = "";
      len = 0;
    }
    cur += ch;
    len += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

const compact = (isoDate: string) => isoDate.replace(/-/g, "");
const stamp = () => new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

export interface CheckinDate {
  day: number;
  date: Date;
}

/** Check-in dates that are today or later, in the user's local calendar. */
export function upcomingCheckins(startedAt: string, days: number[]): CheckinDate[] {
  const today = localISODate();
  return days.map((d) => ({ day: d, date: addDays(startedAt, d) })).filter((c) => localISODate(c.date) >= today);
}

export function buildIcs(trialId: string, productName: string, concern: string, dates: CheckinDate[]): string {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//derm os//Trial check-ins//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
  for (const c of dates) {
    const start = localISODate(c.date);
    const end = localISODate(new Date(c.date.getFullYear(), c.date.getMonth(), c.date.getDate() + 1));
    lines.push(
      "BEGIN:VEVENT",
      `UID:${trialId}-day${c.day}@dermos`,
      `DTSTAMP:${stamp()}`,
      `DTSTART;VALUE=DATE:${compact(start)}`,
      `DTEND;VALUE=DATE:${compact(end)}`,
      `SUMMARY:${esc(`derm//os check-in, day ${c.day}`)}`,
      `DESCRIPTION:${esc(
        `Day ${c.day} check-in for ${productName} (watching ${concern}). Log how your skin feels, then take 2 scans in the same light as your baseline.`
      )}`,
      "BEGIN:VALARM",
      "ACTION:DISPLAY",
      `DESCRIPTION:${esc("derm//os check-in today")}`,
      "TRIGGER:PT9H",
      "END:VALARM",
      "END:VEVENT"
    );
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

export function downloadIcs(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/calendar;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * lib/utils.ts
 * ------------
 * Purpose:    Minimal classnames composition helper (no external deps).
 *             Used to conditionally join CSS module class names.
 * Dependencies: none
 * Scope:      App-wide utility.
 */

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * motion.ts
 * ---------
 * The one exception to the press.
 *
 * Every `Button` steps down a pixel while it is held (`ui/button.tsx`,
 * `active:translate-y-px`): the tactile acknowledgement the owner chose on
 * 2026-09-27 (web/DESIGN.md OD-6). A safety control does not move at all —
 * no press, no animation (M-11, and C-12 for what counts as one: the kill
 * switch, and the three live-order gates on /system).
 *
 * The reason is what a press says. It acknowledges a click, not a result: the
 * button has been pushed, and nothing more. On most controls that is useful,
 * because the result follows on its own. On the kill switch the only thing an
 * operator under stress should read as "done" is the switch's own reported
 * state — the chip turning to "stopped", and the sentence under it saying what
 * became of the orders at the venue — and a control that answers the hand
 * before the system has answered is a small false reassurance at exactly the
 * wrong moment. So the controls there do one thing, visibly, when the API
 * says so.
 *
 * Use it as a Button's `className` (or inside `cn()` with other classes):
 *
 *     <Button variant="destructive" className={STILL} onClick={engage}>
 *
 * `cn()` merges with tailwind-merge, which reads `active:translate-y-0` and
 * the press's `active:translate-y-px` as one property under one variant and
 * keeps the later — the caller's — so only this class reaches the DOM. Two
 * conflicting classes left side by side would leave the winner to the order
 * Tailwind happens to emit them in.
 *
 * tests/unit/test_web_taste.py holds every Button in /system's kill-switch
 * and live-gate cards to it.
 */
export const STILL = "active:translate-y-0";

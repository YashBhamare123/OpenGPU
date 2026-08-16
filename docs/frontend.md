# Frontend

The frontend is plain HTML, CSS, and JavaScript served directly by FastAPI. There is no package manager, bundler, framework, or external calendar dependency.

## Structure

- `index.html` defines login, booking controls, timeline, notices, and confirmation/cancellation dialogs.
- `app.css` owns the visual system, responsive behavior, timeline geometry, reservation states, and motion.
- `app.js` owns browser state, API calls, date calculations, rendering, polling, and event handlers.
- `admin.html`, `admin.css`, and `admin.js` provide the server-authorized admin view for user allowlisting, booking on behalf of users through the same composer/timeline/review flow, reservation-owner search, explicit duration overrides, and cancellation.

The global state tracks the authenticated user, reservations, viewed date, live selection, pending confirmation, refresh timers, provisioning polling, and the reservation selected for cancellation.

## Main flows

- On load, `/me` determines whether to show login or the booking application.
- Login requests and verifies a code (emailed, or printed on the host for administrators when SMTP is skipped), then reloads user and reservation state.
- When `/me` reports `self_booking` false, the booking composer stays locked for non-administrators.
- The seven-day strip changes the viewed day; top arrows move by week.
- The 24-hour timeline renders availability, other reservations, the user's reservation, and the live selection.
- Start time accepts any minute. Duration changes in 15-minute increments from 15 minutes to the `RESERVATION_LIMIT_MINUTES` value returned by `/me`.
- The selection is validated in the browser before the confirmation dialog opens; PostgreSQL remains authoritative.
- Reservation submission sends a unique `Idempotency-Key` and polls `/me` while provisioning rotates credentials.
- Reservations refresh every 30 seconds. A `401` returns the UI to login.

## Rendering and styling

Timeline positions are percentages of a local calendar day. Keep date arithmetic based on `Date` objects rather than string offsets so displayed times follow the browser timezone. Reservation blocks must remain view-only; booking is controlled by the separate composer.

Use existing CSS variables, spacing, typography, borders, shadows, state colors, and reduced-motion behavior. Preserve semantic labels, keyboard controls, live regions, dialog focus behavior, and disabled states. Do not replace the custom timeline with FullCalendar or another large calendar dependency without an explicit architectural decision.

When changing static assets, update the query-string version in `index.html` so browsers do not keep stale CSS or JavaScript.

## Testing changes

Routine tests cover API contracts rather than browser rendering. Frontend changes require manual checks for:

- Fresh login and page refresh with an active session
- Loading, empty, conflict, error, confirmed, and locked states
- Exact-minute start entry and keyboard arrows
- Duration bounds and midnight crossing
- Week navigation and return-to-today behavior
- Live selection alignment across the full timeline
- Cancellation and immediate refresh
- Mobile layout, keyboard navigation, and reduced motion

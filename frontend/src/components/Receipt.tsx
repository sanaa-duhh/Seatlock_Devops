import { date, money, time, type Reservation } from '../api';

export function Receipt({ booking }: { booking: Reservation }) {
  return (
    <article className={`receipt ${booking.status === 'cancelled' ? 'cancelled' : ''}`}>
      <div className="receipt-top">
        <span className="eyebrow">SEATLOCK / ADMIT {booking.seats.length}</span>
        <span className="status-pill">{booking.status}</span>
      </div>
      <h2>{booking.event.title}</h2>
      <p>
        {booking.event.venue}, {booking.event.city}
      </p>
      <div className="receipt-grid">
        <div>
          <small>DATE & TIME</small>
          <strong>
            {date(booking.event.starts_at)} · {time(booking.event.starts_at)}
          </strong>
        </div>
        <div>
          <small>SEATS</small>
          <strong>{booking.seats.join(', ')}</strong>
        </div>
      </div>
      <div className="receipt-bottom">
        <span>
          <small>BOOKING REFERENCE</small>
          <strong>{booking.reference}</strong>
        </span>
        <strong>{money(booking.total_paise)}</strong>
      </div>
      <div className="barcode" aria-hidden="true" />
      <small className="receipt-disclaimer">DEMO TICKET · NOT VALID FOR ADMISSION</small>
    </article>
  );
}

import { useEffect, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  Clock3,
  Info,
  MapPin,
  ShieldCheck,
} from 'lucide-react';
import { api, date, money, time, type Event, type Reservation, type Seat } from '../api';
import { Poster } from '../components/Poster';
import { Receipt } from '../components/Receipt';

export function EventPage({ event }: { event: Event }) {
  const [seats, setSeats] = useState<Seat[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [hold, setHold] = useState<Reservation | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(Date.now());
  const [loaded, setLoaded] = useState(false);
  async function refresh() {
    try {
      const data = await api<{ seats: Seat[] }>(`/events/${event.id}/seats`);
      setSeats(data.seats);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
    const saved = sessionStorage.getItem(`seatlock.hold.${event.id}`);
    if (saved)
      api<Reservation>(`/holds/${saved}`)
        .then((h) => {
          if (h.status === 'active') setHold(h);
          else sessionStorage.removeItem(`seatlock.hold.${event.id}`);
        })
        .catch(() => sessionStorage.removeItem(`seatlock.hold.${event.id}`));
    const poll = window.setInterval(() => void refresh(), 5000);
    const timer = window.setInterval(() => setTick(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(timer);
    };
  }, [event.id]);
  const remaining = hold ? Math.max(0, Math.ceil((new Date(hold.expires_at).getTime() - tick) / 1000)) : 0;
  const expired = hold?.status === 'active' && remaining === 0;
  const chosen = seats.filter((s) => selected.includes(s.id));
  async function reserve() {
    setBusy(true);
    setError('');
    try {
      const h = await api<Reservation>('/holds', {
        method: 'POST',
        body: JSON.stringify({ event_id: event.id, seat_ids: selected }),
      });
      setHold(h);
      sessionStorage.setItem(`seatlock.hold.${event.id}`, h.id);
      setSelected([]);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
      setSelected([]);
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!hold) return;
    setBusy(true);
    setError('');
    try {
      setHold(await api<Reservation>(`/holds/${hold.id}/confirm`, { method: 'POST' }));
      sessionStorage.removeItem(`seatlock.hold.${event.id}`);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function release() {
    if (!hold) return;
    setBusy(true);
    setError('');
    try {
      await api(`/holds/${hold.id}`, { method: 'DELETE' });
      setHold(null);
      sessionStorage.removeItem(`seatlock.hold.${event.id}`);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (hold?.status === 'confirmed')
    return (
      <div className="confirmation">
        <span className="success-icon">
          <CheckCircle2 size={36} />
        </span>
        <div className="eyebrow">YOU’RE ON THE LIST</div>
        <h1>
          Consider your night <em>sorted.</em>
        </h1>
        <p>Your demo booking is confirmed. No payment was taken.</p>
        <Receipt booking={hold} />
        <a href="#/tickets" className="primary">
          View my tickets <ArrowRight size={18} />
        </a>
      </div>
    );
  return (
    <>
      <a href="#/" className="back">
        <ArrowLeft size={16} />
        Back to experiences
      </a>
      <section className="event-heading">
        <div>
          <div className="eyebrow">{event.category.toUpperCase()} / LIVE EXPERIENCE</div>
          <h1>
            {event.title}
            <span>.</span>
          </h1>
          <div className="event-facts">
            <span>
              <CalendarDays size={17} />
              {date(event.starts_at, { weekday: 'short', day: 'numeric', month: 'long' })}
            </span>
            <span>
              <Clock3 size={17} />
              {time(event.starts_at)} IST
            </span>
            <span>
              <MapPin size={17} />
              {event.venue}, {event.city}
            </span>
          </div>
          <p>{event.description}</p>
        </div>
        <div className="mini-poster">
          <Poster event={event} />
        </div>
      </section>
      <div className="booking-layout">
        <section className="seat-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">THE BEST SPOT IS YOUR SPOT</div>
              <h2>Pick your seats</h2>
            </div>
            <span className="capacity">Up to 6 per booking</span>
          </div>
          <div className="stage">
            S T A G E<span>All eyes this way</span>
          </div>
          {!loaded ? (
            <div className="loading">Loading seat availability…</div>
          ) : (
            <div className="seat-map" aria-label="Seat map">
              {'ABCDEF'.split('').map((row) => (
                <div className="seat-row" key={row}>
                  <span className="row-label">{row}</span>
                  {seats
                    .filter((s) => s.row === row)
                    .map((seat) => (
                      <button
                        key={seat.id}
                        className={`seat ${seat.status} ${selected.includes(seat.id) ? 'picked' : ''} ${seat.number === 7 ? 'aisle' : ''}`}
                        aria-label={`Seat ${seat.label}, ${selected.includes(seat.id) ? 'selected' : seat.status}`}
                        aria-pressed={selected.includes(seat.id)}
                        disabled={seat.status !== 'available' || !!hold || busy}
                        onClick={() => {
                          setError('');
                          if (selected.includes(seat.id))
                            setSelected(selected.filter((id) => id !== seat.id));
                          else if (selected.length < 6) setSelected([...selected, seat.id]);
                          else setError('You can select up to 6 seats per booking.');
                        }}
                      >
                        {selected.includes(seat.id) ? <Check size={12} /> : seat.number}
                      </button>
                    ))}
                  <span className="row-label">{row}</span>
                </div>
              ))}
            </div>
          )}
          <div className="seat-legend">
            <span>
              <i />
              Available
            </span>
            <span>
              <i className="picked" />
              Selected
            </span>
            <span>
              <i className="yours" />
              Your hold
            </span>
            <span>
              <i className="booked" />
              Unavailable
            </span>
          </div>
          <div className="seat-note">
            <Info size={15} />
            Availability refreshes every 5 seconds. Seats are secured when you reserve.
          </div>
        </section>
        <aside className="order-panel">
          <div className="eyebrow">YOUR NEXT GOOD NIGHT</div>
          <h2>{hold ? 'Your seats are held.' : 'Make it a plan.'}</h2>
          <p className="order-event">
            {event.title}
            <span>
              {date(event.starts_at)} · {time(event.starts_at)} IST
            </span>
          </p>
          {hold ? (
            <>
              <div className={`hold-timer ${expired ? 'expired' : ''}`}>
                <Clock3 size={19} />
                <span>
                  {expired ? 'Your hold has expired' : 'Reserved just for you'}
                  <small>
                    {expired ? 'Choose your seats again.' : 'Finish booking before the timer ends.'}
                  </small>
                </span>
                <strong>
                  {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')}
                </strong>
              </div>
              <div className="chosen-seats">
                {hold.seats.map((s) => (
                  <span key={s}>{s}</span>
                ))}
              </div>
            </>
          ) : (
            <>
              <p className="selection-label">YOUR SEATS</p>
              <div className="chosen-seats">
                {chosen.length ? (
                  chosen.map((s) => <span key={s.id}>{s.label}</span>)
                ) : (
                  <p>Choose a spot on the map.</p>
                )}
              </div>
            </>
          )}
          <div className="price-row">
            <span>
              {hold ? hold.seats.length : chosen.length} ×{' '}
              {money(hold ? hold.total_paise / hold.seats.length : event.price_paise)}
            </span>
            <strong>{money(hold ? hold.total_paise : chosen.length * event.price_paise)}</strong>
          </div>
          <div className="price-row total">
            <span>Total</span>
            <strong>{money(hold ? hold.total_paise : chosen.length * event.price_paise)}</strong>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {hold ? (
            <>
              {!expired && (
                <button className="primary full" onClick={() => void confirm()} disabled={busy}>
                  {busy ? 'Working…' : 'Confirm demo booking'}
                  <ArrowRight size={17} />
                </button>
              )}
              <button className="secondary full" onClick={() => void release()} disabled={busy}>
                {expired ? 'Choose seats again' : 'Release seats & change selection'}
              </button>
            </>
          ) : (
            <button className="primary full" onClick={() => void reserve()} disabled={!chosen.length || busy}>
              {busy ? 'Reserving…' : 'Hold my seats'}
              <ArrowRight size={17} />
            </button>
          )}
          <div className="checkout-note">
            <ShieldCheck size={16} />
            <span>
              Demo checkout only.
              <br />
              No card details. No real charge.
            </span>
          </div>
        </aside>
      </div>
    </>
  );
}

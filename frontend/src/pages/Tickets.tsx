import { useEffect, useState } from 'react';
import { ArrowRight, Info, Ticket } from 'lucide-react';
import { api, type Reservation } from '../api';
import { Receipt } from '../components/Receipt';

export function Tickets() {
  const [bookings, setBookings] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [cancelId, setCancelId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      setBookings(await api<Reservation[]>('/bookings'));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function cancel() {
    setBusy(true);
    try {
      await api(`/bookings/${cancelId}/cancel`, { method: 'POST' });
      setCancelId(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="tickets-page">
      <div className="eyebrow">PLANS WORTH KEEPING</div>
      <h1>
        Your next <em>“I was there.”</em>
      </h1>
      <p>All your demo bookings, in one little corner of the internet.</p>
      <div className="privacy-note">
        <Info size={16} />
        Guest tickets belong to this browser. Clearing its cookies removes your access.
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {loading ? (
        <div className="loading">Loading your tickets…</div>
      ) : bookings.length === 0 ? (
        <div className="empty">
          <Ticket size={40} />
          <h2>A good night is waiting.</h2>
          <p>Your first ticket belongs right here.</p>
          <a href="#/" className="primary">
            Explore experiences <ArrowRight size={17} />
          </a>
        </div>
      ) : (
        <div className="tickets-grid">
          {bookings.map((b) => (
            <div key={b.id}>
              <Receipt booking={b} />
              {b.status === 'confirmed' &&
                (cancelId === b.id ? (
                  <div className="cancel-confirm">
                    <p>Cancel this demo booking and release the seats?</p>
                    <button className="danger" disabled={busy} onClick={() => void cancel()}>
                      Yes, cancel booking
                    </button>
                    <button className="text-button" disabled={busy} onClick={() => setCancelId(null)}>
                      Keep my tickets
                    </button>
                  </div>
                ) : (
                  <button className="text-button cancel-button" onClick={() => setCancelId(b.id)}>
                    Cancel booking
                  </button>
                ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

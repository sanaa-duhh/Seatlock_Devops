import { useEffect, useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Clock3,
  Compass,
  Info,
  MapPin,
  Search,
  ShieldCheck,
  Ticket,
  X,
} from 'lucide-react';
import { api, date, money, time, type Event } from './api';
import { Poster } from './components/Poster';
import { EventPage } from './pages/EventPage';
import { Tickets } from './pages/Tickets';

const BUILD_VERSION = (import.meta.env.VITE_APP_VERSION || 'dev').slice(0, 7);

export function App() {
  const [route, setRoute] = useState(location.hash || '#/');
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('All events');
  const [search, setSearch] = useState('');
  const [city, setCity] = useState('All cities');
  useEffect(() => {
    const change = () => {
      setRoute(location.hash || '#/');
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  async function load() {
    setLoading(true);
    setError('');
    try {
      await api('/session');
      setEvents(await api<Event[]>('/events'));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  const selected = route.startsWith('#/events/')
    ? events.find((e) => e.id === Number(route.split('/')[2]))
    : undefined;
  const isTickets = route === '#/tickets';
  const filtered = events.filter(
    (e) =>
      (category === 'All events' || e.category === category) &&
      (city === 'All cities' || e.city === city) &&
      `${e.title} ${e.venue} ${e.city}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="SeatLock home">
          <span className="brand-icon">
            <Ticket size={23} />
          </span>
          seatlock<span className="brand-dot">.</span>
        </a>
        <div className="nav-label">MAKE PLANS</div>
        <nav aria-label="Main navigation">
          <a href="#/" className={!isTickets ? 'active' : ''}>
            <Compass size={19} />
            Discover
            <ArrowUpRight className="nav-arrow" size={15} />
          </a>
          <a href="#/tickets" className={isTickets ? 'active' : ''}>
            <Ticket size={19} />
            My tickets
          </a>
        </nav>
        <div className="sidebar-note">
          <span className="spark">✳</span>
          <h3>
            Good nights
            <br />
            start with a plan.
          </h3>
          <p>
            A front-row feeling.
            <br />A story for tomorrow.
          </p>
          <a href="#/">
            Find your next one <ArrowRight size={16} />
          </a>
        </div>
        <div className="sidebar-footer">
          <span className="avatar">G</span>
          <div>
            <strong>Your guest space</strong>
            <span>Tickets saved in this browser</span>
          </div>
        </div>
        <div className="build-tag" title="Commit this build was made from">
          build {BUILD_VERSION}
        </div>
      </aside>
      <div className="page">
        <header className="topbar">
          <span className="breadcrumb">YOUR NEXT GOOD MEMORY STARTS HERE</span>
          <div className="topbar-right">
            <MapPin size={15} />
            <label className="sr-only" htmlFor="city">
              Filter by city
            </label>
            <select
              id="city"
              value={city}
              onChange={(e) => {
                setCity(e.target.value);
                location.hash = '#/';
              }}
            >
              <option>All cities</option>
              {[...new Set(events.map((e) => e.city))].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <span className="demo-badge">LIVE ON EKS</span>
          </div>
        </header>
        <main id="main">
          {loading ? (
            <div className="loading">
              <span className="spinner" />
              Finding your next great night…
            </div>
          ) : error ? (
            <div className="empty">
              <Info />
              <h1>We couldn’t load the events.</h1>
              <p>{error}</p>
              <button className="primary" onClick={() => void load()}>
                Try again
              </button>
            </div>
          ) : isTickets ? (
            <Tickets />
          ) : selected ? (
            <EventPage key={selected.id} event={selected} />
          ) : route.startsWith('#/events/') ? (
            <div className="empty">
              <h1>Event not found</h1>
              <a href="#/">Explore other events</a>
            </div>
          ) : (
            <>
              <section className="hero">
                <div className="hero-copy">
                  <div className="eyebrow">
                    <span /> GO OUT. TUNE IN. BE THERE.
                  </div>
                  <h1>
                    Less scrolling.
                    <br />
                    More <span>living.</span>
                    <svg viewBox="0 0 260 20" aria-hidden="true">
                      <path d="M3 14 Q112 -5 256 11" />
                    </svg>
                  </h1>
                  <p>
                    The live music, big laughs, and little moments
                    <br className="desktop-break" /> that make your calendar worth opening.
                  </p>
                  <a
                    className="primary"
                    href="#events"
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById('events')?.scrollIntoView({ behavior: 'smooth' });
                    }}
                  >
                    Find your next experience <ArrowDown size={17} />
                  </a>
                  <div className="hero-foot">
                    <ShieldCheck size={16} />
                    Pick your seat. We’ll hold your spot.
                  </div>
                </div>
                {events[0] && (
                  <a
                    href={`#/events/${events[0].id}`}
                    className="featured"
                    aria-label={`Explore ${events[0].title}`}
                  >
                    <div className="featured-sticker">
                      THE NEXT
                      <br />
                      <strong>GOOD NIGHT ↗</strong>
                    </div>
                    <Poster event={events[0]} large />
                    <div className="featured-caption">
                      <span>IN THE SPOTLIGHT</span>
                      <strong>{events[0].title}</strong>
                      <span>
                        {date(events[0].starts_at)} · {events[0].venue}
                      </span>
                      <span className="circle-arrow">
                        <ArrowUpRight />
                      </span>
                    </div>
                  </a>
                )}
              </section>
              <section className="events-section" id="events">
                <div className="section-heading">
                  <div className="eyebrow">CURATED FOR YOUR CALENDAR</div>
                  <div className="heading-row">
                    <h2>
                      Find your kind of <em>live.</em>
                    </h2>
                    <label className="search">
                      <Search size={17} />
                      <input
                        aria-label="Search events"
                        placeholder="Search events, venues…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                      {search && (
                        <button aria-label="Clear search" onClick={() => setSearch('')}>
                          <X size={14} />
                        </button>
                      )}
                    </label>
                  </div>
                </div>
                <div className="filter-row">
                  <div className="tabs" aria-label="Event categories">
                    {['All events', 'Music', 'Comedy', 'Theatre', 'Talks'].map((c) => (
                      <button
                        key={c}
                        aria-pressed={c === category}
                        className={c === category ? 'selected' : ''}
                        onClick={() => setCategory(c)}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                  <span className="result-count">{filtered.length} experiences</span>
                </div>
                <div className="event-grid">
                  {filtered.map((event) => (
                    <a className="event-card" href={`#/events/${event.id}`} key={event.id}>
                      <Poster event={event} />
                      <div className="card-detail">
                        <div className="card-meta">
                          <span>
                            {date(event.starts_at)} · {time(event.starts_at)}
                          </span>
                          <span>{event.category}</span>
                        </div>
                        <h3>{event.title}</h3>
                        <p>
                          <MapPin size={13} />
                          {event.venue}, {event.city}
                        </p>
                        <div className="card-bottom">
                          <span>
                            From <strong>{money(event.price_paise)}</strong>
                          </span>
                          <span className="card-cta">
                            Pick a seat <ArrowUpRight size={16} />
                          </span>
                        </div>
                      </div>
                    </a>
                  ))}
                </div>
                {filtered.length === 0 && (
                  <div className="empty">
                    <Search />
                    <h3>No events found</h3>
                    <p>Try a different search, city, or category.</p>
                    <button
                      className="secondary"
                      onClick={() => {
                        setSearch('');
                        setCity('All cities');
                        setCategory('All events');
                      }}
                    >
                      Reset filters
                    </button>
                  </div>
                )}
              </section>
              <section className="promise-strip">
                <div>
                  <Ticket />
                  <span>
                    <strong>Your seat. Actually yours.</strong>
                    <small>Reserved while you finish booking.</small>
                  </span>
                </div>
                <div>
                  <Clock3 />
                  <span>
                    <strong>A little breathing room.</strong>
                    <small>Five minutes to make it official.</small>
                  </span>
                </div>
                <div>
                  <ShieldCheck />
                  <span>
                    <strong>Try the whole experience.</strong>
                    <small>Demo checkout. No real payments.</small>
                  </span>
                </div>
              </section>
            </>
          )}
        </main>
        <footer className="footer">
          <span>
            seatlock. <span>Be there.</span>
          </span>
          <p>Fictional events · Demo bookings · No payments collected</p>
          <span>MADE FOR MOMENTS ↗</span>
        </footer>
      </div>
    </div>
  );
}

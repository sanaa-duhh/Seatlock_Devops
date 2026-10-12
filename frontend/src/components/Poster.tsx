import { ArrowUpRight } from 'lucide-react';
import { date, type Event } from '../api';

export function Poster({ event, large = false }: { event: Event; large?: boolean }) {
  return (
    <div className={`poster ${event.theme} ${large ? 'large' : ''}`} aria-hidden="true">
      <div className="poster-top">
        <span>SEATLOCK SELECTS</span>
        <span>LIVE / {date(event.starts_at, { month: 'short' }).toUpperCase()}</span>
      </div>
      <div className="poster-art">
        <i />
        <i />
        <i />
        <i />
        <i />
      </div>
      <div className="poster-title">
        {event.title.split(' ').map((word, i) => (
          <span key={i}>{word}</span>
        ))}
      </div>
      <div className="poster-bottom">
        <span>
          {event.category.toUpperCase()} · {event.city.toUpperCase()}
        </span>
        <ArrowUpRight size={20} />
      </div>
    </div>
  );
}

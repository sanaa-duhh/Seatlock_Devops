export type Event = {
  id: number;
  slug: string;
  title: string;
  category: string;
  venue: string;
  city: string;
  starts_at: string;
  description: string;
  theme: string;
  price_paise: number;
};
export type Seat = {
  id: number;
  row: string;
  number: number;
  label: string;
  status: 'available' | 'held' | 'yours' | 'booked';
};
export type Reservation = {
  id: string;
  status: string;
  expires_at: string;
  created_at: string;
  reference: string | null;
  total_paise: number;
  seats: string[];
  event: Event;
};

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Seatlock-Request': '1', ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : 'That request could not be completed. Please try again.',
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const money = (paise: number) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(paise / 100);
export const date = (
  value: string,
  options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' },
) => new Date(value).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', ...options });
export const time = (value: string) =>
  new Date(value).toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: 'numeric',
    minute: '2-digit',
  });

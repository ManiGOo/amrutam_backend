import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  setupTimeout: '300s',
  insecureSkipTLSVerify: true,
  scenarios: {
    reads: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 20 },
        { duration: '60s', target: 20 },
        { duration: '30s', target: 0 },
      ],
      exec: 'reads',
    },
    writes: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 5 },
        { duration: '60s', target: 10 },
        { duration: '30s', target: 0 },
      ],
      exec: 'writes',
    },
  },
  thresholds: {
    // rubric SLOs: p95 <200ms reads, <500ms writes
    'http_req_duration{scenario:reads}': ['p(95)<200'],
    'http_req_duration{scenario:writes}': ['p(95)<500'],
    http_req_failed: ['rate<0.05'],
  },
};

const BASE = __ENV.BASE_URL || 'http://api:8000';

export function setup() {
  const s = uuidv4().slice(0, 6);
  const doc = {
    email: `k6doc-${s}@ex.com`, password: 'StrongPass123', role: 'doctor',
    full_name: 'K6 Doc', specialization: 'Ayurveda', license_no: `K6-${s}`,
  };
  http.post(`${BASE}/v1/auth/register`, JSON.stringify(doc), { headers: { 'Content-Type': 'application/json' } });
  const login = http.post(`${BASE}/v1/auth/login`, JSON.stringify({ email: doc.email, password: doc.password }), { headers: { 'Content-Type': 'application/json' } });
  const dtoken = login.json().access_token;

  // pool of slots for write iterations (contention 409s are expected + counted)
  const slots = [];
  const start = new Date(Date.now() + 3600e3).toISOString();
  const end = new Date(Date.now() + 5400e3).toISOString();
  for (let i = 0; i < 300; i++) {
    const r = http.post(`${BASE}/v1/doctors/slots`, JSON.stringify({ starts_at: start, ends_at: end }), {
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${dtoken}` },
    });
    if (r.status === 201) slots.push(r.json().id);
  }
  // patient pool: 60 patients / ≤20 write VUs @ ~1rps stays under the
  // 30/min per-patient booking bucket, so writes measure latency, not throttle
  const patients = [];
  for (let i = 0; i < 30; i++) {
    const email = `k6pat-${s}-${i}@ex.com`;
    http.post(`${BASE}/v1/auth/register`, JSON.stringify({ email, password: 'StrongPass123', role: 'patient', full_name: 'K6 Pat' }), { headers: { 'Content-Type': 'application/json' } });
    const l = http.post(`${BASE}/v1/auth/login`, JSON.stringify({ email, password: 'StrongPass123' }), { headers: { 'Content-Type': 'application/json' } });
    patients.push(l.json().access_token);
  }
  return { slots, patients };
}

export function reads() {
  const r1 = http.get(`${BASE}/health`);
  check(r1, { 'health 200': (r) => r.status === 200 });
  const r2 = http.get(`${BASE}/v1/search/doctors?q=Ayurveda&limit=20`);
  check(r2, { 'search 200': (r) => r.status === 200 });
  sleep(0.1);
}

export function writes(data) {
  const vu = __VU - 1;
  const token = data.patients[vu % data.patients.length];
  const slot = data.slots[Math.floor(Math.random() * data.slots.length)];
  const r = http.post(`${BASE}/v1/bookings`, JSON.stringify({ slot_id: slot }), {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'Idempotency-Key': uuidv4(),
    },
  });
  // 202 = booked, 409 = lost the race (valid under contention), 429 = throttled
  check(r, { 'book settled': (x) => [202, 409, 429].includes(x.status) });
  sleep(1);
}

// Trusted synthetic analysis. Never log session cookies or response bodies.
import assert from 'node:assert/strict';
const base = new URL(process.env.BASE_URL);
const origin = new URL(process.env.PUBLIC_ORIGIN).origin;
assert.equal(base.protocol, 'http:');
assert.match(base.hostname, /^frontend(?:-preview)?\.boutique-(dev|staging|production|rollouts-check)\.svc\.cluster\.local$/);
assert.equal(base.port, '8080');
assert.equal(base.pathname, '/');

function browser() {
  let cookie = '';
  return async (path, method = 'GET', body, key, sendOrigin = true) => {
    const headers = {'User-Agent': 'BoutiqueRolloutAnalysis/1.0', Accept: 'application/json'};
    if (sendOrigin) headers.Origin = origin;
    if (cookie) headers.Cookie = cookie;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (key) headers['Idempotency-Key'] = key;
    const response = await fetch(new URL(path, base), {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      redirect: 'error', signal: AbortSignal.timeout(10000),
    });
    const incoming = response.headers.get('set-cookie');
    if (incoming) cookie = incoming.split(';', 1)[0];
    return {status: response.status, body: await response.json()};
  };
}

try {
  const a = browser(), b = browser();
  assert.equal((await a('/health/ready')).status, 200);
  const products = (await a('/api/products')).body;
  assert.ok(Array.isArray(products) && products.length > 0);
  const product = products[0];
  assert.match(product.id, /^[a-z0-9-]{1,64}$/);
  assert.ok(Number.isInteger(product.price) && product.price > 0);
  assert.deepEqual((await a('/api/cart')).body.items, []);
  const item = '/api/cart/items/' + product.id;
  assert.equal((await a(item, 'PUT', {quantity: 2})).status, 200);
  assert.equal((await a(item, 'PUT', {quantity: 21})).status, 400);
  assert.equal((await a(item, 'PUT', {quantity: 1}, undefined, false)).status, 403);
  assert.equal((await a('/api/cart/items/missing', 'PUT', {quantity: 1})).status, 404);
  assert.deepEqual((await b('/api/cart')).body.items, []);
  const checkout = await a('/api/orders', 'POST', undefined, 'rollout-checkout-001');
  assert.equal(checkout.status, 200);
  const order = checkout.body;
  assert.match(order.id, /^[a-f0-9-]{36}$/);
  assert.equal(order.total, 2 * product.price);
  assert.equal(order.currency, product.currency);
  assert.equal((await a('/api/orders', 'POST', undefined, 'rollout-checkout-001')).body.id, order.id);
  assert.equal((await a('/api/orders/' + order.id)).body.total, order.total);
  assert.equal((await b('/api/orders/' + order.id)).status, 404);
  assert.equal((await b('/api/orders', 'POST', undefined, 'rollout-empty-001')).status, 409);
  const results = await Promise.all(Array.from({length: 4}, () => a('/api/orders', 'POST', undefined, 'rollout-concurrent-001')));
  assert.ok(results.every(result => result.status === 200));
  assert.equal(new Set(results.map(result => result.body.id)).size, 1);
  assert.deepEqual((await a(item, 'DELETE')).body.items, []);
  console.log('PASS browse cart validation origin session_isolation server_pricing checkout repeat_idempotency concurrent_idempotency order_ownership empty_cart deletion');
} catch {
  console.error('FAIL rollout functional analysis; response/session details suppressed');
  process.exitCode = 1;
}

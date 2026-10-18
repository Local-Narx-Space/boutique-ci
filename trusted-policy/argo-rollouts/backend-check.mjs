// Trusted candidate-specific checks; synthetic sessions never share user carts.
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
const service = process.env.SERVICE;
const ports = {catalogue: '8081', cart: '8082', orders: '8083'};
assert.ok(Object.hasOwn(ports, service));
const base = new URL(process.env.BASE_URL);
assert.equal(base.protocol, 'http:');
assert.match(base.hostname, new RegExp('^' + service + '(?:-preview)?\\.boutique-(dev|staging|production|rollouts-check)\\.svc\\.cluster\\.local$'));
assert.equal(base.port, ports[service]);
assert.equal(base.pathname, '/');
const session = randomBytes(32).toString('hex');
async function request(url, path, status=200, method='GET', body, extra={}) {
  const response = await fetch(new URL(path, url), {method,
    headers: {'Content-Type':'application/json', 'X-Session-ID':session, ...extra},
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(10000), redirect:'error'});
  assert.equal(response.status, status);
  return response.json();
}
try {
  assert.equal((await request(base, '/health/ready')).status, 'ok');
  if (service === 'catalogue') {
    const products = await request(base, '/products');
    assert.ok(Array.isArray(products) && products.length > 0);
    for (const p of products) {
      assert.match(p.id, /^[a-z0-9-]{1,64}$/);
      assert.ok(Number.isInteger(p.price) && p.price > 0);
      assert.ok(['USD','INR'].includes(p.currency));
      assert.equal((await request(base, '/products/' + p.id)).price, p.price);
    }
    await request(base, '/products/missing', 404);
  } else {
    const cart = service === 'cart' ? base : new URL('http://cart:8082');
    const path = '/carts/' + session;
    assert.deepEqual((await request(cart, path)).items, []);
    try {
      const product = (await request(new URL('http://catalogue:8081'), '/products'))[0];
      assert.match(product.id, /^[a-z0-9-]{1,64}$/);
      const item = path + '/items/' + product.id;
      assert.equal((await request(cart, item, 200, 'PUT', {quantity:2})).items[0].quantity, 2);
      await request(cart, item, 422, 'PUT', {quantity:21});
      if (service === 'orders') {
        const headers = {'Idempotency-Key':'rollout-' + randomBytes(16).toString('hex')};
        const order = await request(base, '/orders', 200, 'POST', undefined, headers);
        assert.match(order.id, /^[a-f0-9-]{36}$/);
        assert.equal(order.total, 2 * product.price);
        assert.equal(order.currency, product.currency);
        assert.equal((await request(base, '/orders', 200, 'POST', undefined, headers)).id, order.id);
        assert.equal((await request(base, '/orders/' + order.id)).total, order.total);
        await request(base, '/orders/' + order.id, 404, 'GET', undefined, {'X-Session-ID':randomBytes(32).toString('hex')});
      }
    } finally {
      for (const item of (await request(cart, path)).items) {
        await request(cart, path + '/items/' + item.productId, 200, 'DELETE');
      }
    }
    assert.deepEqual((await request(cart, path)).items, []);
  }
  console.log('PASS candidate-specific ' + service + ' functional analysis');
} catch {
  console.error('FAIL candidate-specific functional analysis; response/session details suppressed');
  process.exitCode = 1;
}

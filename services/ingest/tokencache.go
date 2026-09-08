package main

import (
	"container/list"
	"sync"
	"time"
)

// tokenCache is a small, TTL'd LRU of already-verified tokens. argon2id verification is deliberately
// expensive (~tens of ms); without a cache, a busy agent pushing many batches would pay it every
// request and cap ingest throughput. Keyed by "<org>\x00<token>" (the plaintext is secret and never
// leaves the process). Entries expire so a revoked token stops working within the TTL.
type tokenCache struct {
	mu   sync.Mutex
	ll   *list.List
	m    map[string]*list.Element
	cap  int
	ttl  time.Duration
	nowF func() time.Time
}

type cacheEntry struct {
	key     string
	id      identity
	expires time.Time
}

func newTokenCache(capacity int, ttl time.Duration) *tokenCache {
	return &tokenCache{
		ll:   list.New(),
		m:    make(map[string]*list.Element),
		cap:  capacity,
		ttl:  ttl,
		nowF: time.Now,
	}
}

func (c *tokenCache) get(key string) (identity, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	el, ok := c.m[key]
	if !ok {
		return identity{}, false
	}
	ent := el.Value.(*cacheEntry)
	if c.nowF().After(ent.expires) {
		c.removeElement(el)
		return identity{}, false
	}
	c.ll.MoveToFront(el)
	return ent.id, true
}

func (c *tokenCache) put(key string, id identity) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if el, ok := c.m[key]; ok {
		ent := el.Value.(*cacheEntry)
		ent.id = id
		ent.expires = c.nowF().Add(c.ttl)
		c.ll.MoveToFront(el)
		return
	}
	el := c.ll.PushFront(&cacheEntry{key: key, id: id, expires: c.nowF().Add(c.ttl)})
	c.m[key] = el
	if c.ll.Len() > c.cap {
		c.removeElement(c.ll.Back())
	}
}

func (c *tokenCache) removeElement(el *list.Element) {
	if el == nil {
		return
	}
	c.ll.Remove(el)
	delete(c.m, el.Value.(*cacheEntry).key)
}

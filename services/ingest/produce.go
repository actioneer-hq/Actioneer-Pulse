package main

import (
	"context"

	"github.com/twmb/franz-go/pkg/kgo"
)

// producer sends raw-spans records. An interface so tests can substitute an in-memory capture.
type producer interface {
	Send(ctx context.Context, topic string, recs []outRecord) error
	Close()
}

// kafkaProducer is the franz-go-backed producer (pure Go, no cgo).
type kafkaProducer struct {
	client *kgo.Client
}

func newKafkaProducer(brokers []string) (*kafkaProducer, error) {
	cl, err := kgo.NewClient(
		kgo.SeedBrokers(brokers...),
		kgo.ProducerLinger(0), // low-latency: ingest returns 200 only after flush
	)
	if err != nil {
		return nil, err
	}
	return &kafkaProducer{client: cl}, nil
}

// Send produces every record and blocks until all are acked (mirrors produce()'s flush-before-return),
// so the HTTP 200 means the batch is durably on the topic.
func (p *kafkaProducer) Send(ctx context.Context, topic string, recs []outRecord) error {
	krecs := make([]*kgo.Record, len(recs))
	for i, r := range recs {
		headers := make([]kgo.RecordHeader, 0, len(r.Headers))
		for k, v := range r.Headers {
			headers = append(headers, kgo.RecordHeader{Key: k, Value: []byte(v)})
		}
		krecs[i] = &kgo.Record{
			Topic:   topic,
			Key:     []byte(r.Key),
			Value:   r.Value,
			Headers: headers,
		}
	}
	results := p.client.ProduceSync(ctx, krecs...)
	return results.FirstErr()
}

func (p *kafkaProducer) Close() { p.client.Close() }

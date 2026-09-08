# Pulse ingest (Go). Multi-stage: build a static binary, ship it on a distroless base (no shell, no
# package manager — tiny attack surface). Build context is services/ingest/.
FROM golang:1.27 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# CGO off -> a fully static binary that runs on the distroless static image.
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /ingest .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /ingest /ingest
EXPOSE 8000
ENTRYPOINT ["/ingest"]

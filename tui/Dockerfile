FROM golang:1.26-alpine AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /iatreon-tui ./cmd/app

FROM alpine:3.22

WORKDIR /app

ENV TERM=xterm-256color

COPY --from=build /iatreon-tui /usr/local/bin/iatreon-tui

EXPOSE 2222

CMD ["iatreon-tui", "-ssh", "-host", "0.0.0.0", "-port", "2222"]

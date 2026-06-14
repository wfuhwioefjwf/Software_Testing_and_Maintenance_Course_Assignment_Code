FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/golang:1.23-alpine AS builder
WORKDIR /src

COPY go.mod ./
COPY . .

ARG SKAFFOLD_GO_GCFLAGS
RUN CGO_ENABLED=0 GOOS=linux env GOPROXY=https://goproxy.cn,direct go build -gcflags="${SKAFFOLD_GO_GCFLAGS}" -o /promotionservice .

FROM scratch

WORKDIR /src
COPY --from=builder /promotionservice /src/promotionservice

ENV GOTRACEBACK=single

EXPOSE 8080
ENTRYPOINT ["/src/promotionservice"]

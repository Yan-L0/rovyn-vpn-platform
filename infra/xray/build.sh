#!/usr/bin/env bash
# Run with Go 1.26.1, git, Python 3 and OpenSSL installed.
set -Eeuo pipefail
trap 'printf "Build failed at line %s\n" "$LINENO" >&2' ERR
for tool in git go python3 openssl; do
  command -v "$tool" >/dev/null
done
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly build_dir="$(mktemp -d -t rovyn-xray-build.XXXXXXXX)"
readonly revision=d2758a023cd7f4174a5a5fa4ff66e487d4342ba0
printf 'Build directory (retained for audit): %s\n' "$build_dir"
git clone --depth 1 --branch v26.3.27 https://github.com/XTLS/Xray-core.git "$build_dir/source"
cd -- "$build_dir/source"
[[ "$(git rev-parse HEAD)" == "$revision" ]]
git apply --check "$script_dir/device-revocation.patch"
git apply "$script_dir/device-revocation.patch"
cp -- "$script_dir/user_revoke_test.go" common/protocol/user_revoke_test.go
gofmt -w common/protocol/user.go common/protocol/user_revoke_test.go proxy/vless/validator.go proxy/hysteria/account/config.go proxy/vless/inbound/inbound.go transport/internet/hysteria/hub.go
GOMAXPROCS=2 go test -p 2 -race ./common/protocol ./proxy/vless/... ./proxy/vmess/encoding ./proxy/hysteria/... ./transport/internet/hysteria/...
CGO_ENABLED=0 GOMAXPROCS=2 go build -p 2 -trimpath -o "$build_dir/xray-device-revoke" ./main
python3 "$script_dir/../test_session_revocation.py" "$build_dir/xray-device-revoke"
printf 'Verified binary: %s\n' "$build_dir/xray-device-revoke"

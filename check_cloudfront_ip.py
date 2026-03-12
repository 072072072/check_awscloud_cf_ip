#!/usr/bin/env python3
"""
AWS CloudFront IP 대역 확인 스크립트
- AWS 공식 ip-ranges.json을 실시간으로 받아와 CloudFront 대역과 비교
- 텍스트 파일에서 IP를 자동 추출 (형식 자유, 공백/줄바꿈/쉼표 구분 모두 지원)
- 결과를 콘솔 출력 및 CSV 파일로 저장

사용법:
    python check_cloudfront_ip.py <ip목록파일.txt>
    python check_cloudfront_ip.py <ip목록파일.txt> --output result.csv
    python check_cloudfront_ip.py <ip목록파일.txt> --no-save   (CSV 저장 안 함)
"""

import sys
import re
import json
import urllib.request
import ipaddress
import csv
import argparse
from datetime import datetime

AWS_IP_RANGES_URL = "https://ip-ranges.amazonaws.com/ip-ranges.json"


def fetch_cloudfront_ranges() -> tuple[list, list]:
    """AWS 공식 JSON에서 CloudFront IPv4/IPv6 대역 가져오기"""
    print(f"[*] AWS IP 대역 정보 가져오는 중... ({AWS_IP_RANGES_URL})")
    try:
        with urllib.request.urlopen(AWS_IP_RANGES_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[!] AWS IP 대역 다운로드 실패: {e}")
        sys.exit(1)

    ipv4_cf = [
        ipaddress.ip_network(p["ip_prefix"])
        for p in data.get("prefixes", [])
        if p.get("service") == "CLOUDFRONT"
    ]
    ipv6_cf = [
        ipaddress.ip_network(p["ipv6_prefix"])
        for p in data.get("ipv6_prefixes", [])
        if p.get("service") == "CLOUDFRONT"
    ]

    sync_token = data.get("syncToken", "unknown")
    print(f"[*] 데이터 기준 시각: {data.get('createDate', 'N/A')}  (syncToken: {sync_token})")
    print(f"[*] CloudFront IPv4 대역: {len(ipv4_cf)}개 / IPv6 대역: {len(ipv6_cf)}개\n")
    return ipv4_cf, ipv6_cf


def extract_ips_from_text(text: str) -> list[str]:
    """텍스트에서 IP 주소 추출 (IPv4 및 IPv6, CIDR 표기 포함)"""
    # IPv6 (CIDR 포함)
    ipv6_pattern = r'(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(?:/\d{1,3})?'
    # IPv4 (CIDR 포함)
    ipv4_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b'

    found = re.findall(ipv6_pattern, text) + re.findall(ipv4_pattern, text)

    # 중복 제거, 순서 유지
    seen = set()
    unique = []
    for ip in found:
        if ip not in seen:
            seen.add(ip)
            unique.append(ip)
    return unique


def is_cloudfront(ip_str: str, ipv4_ranges: list, ipv6_ranges: list) -> tuple[bool, str, str]:
    """
    IP가 CloudFront 대역인지 확인
    Returns: (is_cf: bool, ip_type: str, matched_cidr: str)
    """
    try:
        addr = ipaddress.ip_address(ip_str.split("/")[0])  # CIDR이면 호스트만 추출
    except ValueError:
        return False, "INVALID", ""

    ip_type = "IPv4" if addr.version == 4 else "IPv6"
    ranges = ipv4_ranges if addr.version == 4 else ipv6_ranges

    for network in ranges:
        if addr in network:
            return True, ip_type, str(network)

    return False, ip_type, ""


def check_ips(ip_list: list, ipv4_ranges: list, ipv6_ranges: list) -> list[dict]:
    """IP 목록 전체 검사"""
    results = []
    for ip_str in ip_list:
        is_cf, ip_type, matched = is_cloudfront(ip_str, ipv4_ranges, ipv6_ranges)
        results.append({
            "ip": ip_str,
            "type": ip_type,
            "is_cloudfront": is_cf,
            "matched_cidr": matched,
        })
    return results


def print_results(results: list[dict]):
    """결과 콘솔 출력"""
    cf_count = sum(1 for r in results if r["is_cloudfront"])
    non_cf = [r for r in results if not r["is_cloudfront"] and r["type"] != "INVALID"]
    invalid = [r for r in results if r["type"] == "INVALID"]

    print("=" * 65)
    print(f"  총 검사 IP: {len(results)}개  |  CloudFront: {cf_count}개  |  비해당: {len(non_cf)}개  |  유효하지않음: {len(invalid)}개")
    print("=" * 65)

    # CloudFront 해당 IP
    cf_list = [r for r in results if r["is_cloudfront"]]
    if cf_list:
        print("\n✅ [CloudFront 대역 해당]")
        for r in cf_list:
            print(f"   {r['ip']:<40} ({r['type']})  →  {r['matched_cidr']}")

    # 비해당 IP
    if non_cf:
        print("\n❌ [CloudFront 대역 비해당]")
        for r in non_cf:
            print(f"   {r['ip']:<40} ({r['type']})")

    # 유효하지 않은 IP
    if invalid:
        print("\n⚠️  [유효하지 않은 IP]")
        for r in invalid:
            print(f"   {r['ip']}")

    print()


def save_csv(results: list[dict], output_path: str):
    """결과를 CSV로 저장"""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["ip", "type", "is_cloudfront", "matched_cidr"])
        writer.writeheader()
        writer.writerows(results)
    print(f"[*] 결과 저장 완료: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="AWS CloudFront IP 대역 확인 도구")
    parser.add_argument("input_file", help="IP 목록이 포함된 텍스트 파일 경로")
    parser.add_argument("--output", "-o", help="CSV 출력 파일 경로 (기본: cf_result_YYYYMMDD_HHMMSS.csv)")
    parser.add_argument("--no-save", action="store_true", help="CSV 저장 생략")
    args = parser.parse_args()

    # 파일 읽기
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print(f"[!] 파일을 찾을 수 없습니다: {args.input_file}")
        sys.exit(1)

    # IP 추출
    ip_list = extract_ips_from_text(text)
    if not ip_list:
        print("[!] 텍스트에서 IP 주소를 찾을 수 없습니다.")
        sys.exit(1)
    print(f"[*] 추출된 IP: {len(ip_list)}개\n")

    # CloudFront 대역 가져오기
    ipv4_ranges, ipv6_ranges = fetch_cloudfront_ranges()

    # 검사
    results = check_ips(ip_list, ipv4_ranges, ipv6_ranges)

    # 결과 출력
    print_results(results)

    # CSV 저장
    if not args.no_save:
        output_path = args.output or f"cf_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        save_csv(results, output_path)


if __name__ == "__main__":
    main()

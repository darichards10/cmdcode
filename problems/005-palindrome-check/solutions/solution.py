s = input().strip()
print("YES" if s.lower() == s.lower()[::-1] else "NO")

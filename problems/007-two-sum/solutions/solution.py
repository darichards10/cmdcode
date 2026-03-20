n = int(input())
nums = list(map(int, input().split()))
target = int(input())
seen = {}
for i, x in enumerate(nums):
    complement = target - x
    if complement in seen:
        print(seen[complement], i)
        break
    seen[x] = i

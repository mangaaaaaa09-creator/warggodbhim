import requests
bio = input("Enter Bio: ")
token = input("Enter Token: ")
url = f"https://foxlongbio.vercel.app/encrypt?bio={bio}&token={token}"
res = requests.get(url)
print(res.json())
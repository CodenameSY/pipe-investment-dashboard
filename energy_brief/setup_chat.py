"""Local-only helper: never save or echo the token."""
import getpass
import json
import urllib.request


def main():
    print('BotFather 토큰을 입력하세요(화면에 표시하지 않습니다). 먼저 봇에 /start를 보내세요.')
    token = getpass.getpass('Bot token: ').strip()
    try:
        request = urllib.request.Request(
            'https://api.telegram.org/bot' + token + '/getUpdates',
            data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.load(response)
        if not body.get('ok'):
            raise ValueError()
        chats = {}
        for update in body['result']:
            message = update.get('message') or update.get('channel_post') or {}
            chat = message.get('chat') or {}
            if 'id' in chat:
                chats[chat['id']] = chat.get('title') or chat.get('first_name') or chat.get('type')
        for chat_id, label in chats.items():
            print(f'{label}: {chat_id}')
        if not chats:
            print('채팅 없음: 봇에 /start를 보낸 후 다시 실행하세요. 다른 프로그램이 getUpdates를 소비하는지도 확인하세요.')
    except Exception:
        print('조회 실패: 토큰, 네트워크, 기존 webhook 설정을 확인하세요. 비밀값 보호를 위해 응답은 출력하지 않습니다.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

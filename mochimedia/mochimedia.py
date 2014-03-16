import json


def main():
    with open('mochimedia.json', 'r') as in_file:
        # keys: generated offset limit total games
        feed_obj = json.load(in_file)

    for game_obj in feed_obj['games']:
        for value in game_obj.values():
            if isinstance(value, str) \
            and (value.startswith('http://') or value.startswith('https://')):

                if 'http:// ' in value:
                    value = value.replace('http:// ', 'http://')

                if '\n' in value:
                    value = value.split('\n', 1)[0]

                value = value.strip()
                value = value.replace(' ', '%20')

                print(value)


if __name__ == '__main__':
    main()

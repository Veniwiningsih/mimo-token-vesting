# MiMo Token Vesting

Token vesting schedule calculator and tracker. Built with **MiMo V2.5**.

## Features

- Cliff + linear vesting with multiple categories
- Token release tracking with SQLite persistence
- Multi-batch schedule management
- Category-based grouping (team, advisor, investor, ecosystem)

## Usage

```bash
python vesting.py --summary
python vesting.py --check 0xTeam1 --day 150
```

## License

MIT

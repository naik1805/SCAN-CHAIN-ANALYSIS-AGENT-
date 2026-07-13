# Data folder

Drop your real test files here. The app auto-detects them under
**Data source → Local data folder** in the sidebar.

```
data/
├── logs/
│   ├── LOT_1_.../   log_01.log ... log_15.log
│   ├── LOT_2_.../   ...
│   └── ...          (lots are auto-discovered recursively)
└── stil/            <-- put STIL configs here (.stil)
```

Logs are discovered recursively, so the per-lot subfolder layout works as-is. After
placing files, choose **Local data folder** in the sidebar, pick the lots, and set the
max logs per lot. Nothing here is required to run the app — the mock simulation works
without any files.

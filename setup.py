from setuptools import setup, find_packages

setup(
    name="dsn-harness",
    version="0.4.0",
    description="General-purpose Agent Harness framework & embedded SDK",
    author="DSN Team",
    packages=find_packages(include=["harness", "harness.*"]),
    python_requires=">=3.10",
    install_requires=[
        "openai>=1.0.0",
        "requests>=2.28.0",
        "PyYAML>=6.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "full": [
            "flask>=3.0.0",
            "fastapi>=0.100",
            "uvicorn>=0.20",
            "numpy>=1.24.0",
            "cryptography>=40.0.0",
            "rich>=13.0.0",
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)

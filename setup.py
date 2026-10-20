from setuptools import setup, find_packages

setup(
    name="aicf",
    version="0.5.0",
    description="AICF — Agent Infrastructure Cybernetics Framework",
    author="DSN Team",
    packages=find_packages(include=["harness", "harness.*", "infra", "infra.*"]),
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
            "psutil>=5.9",
            "opencv-python>=4.8",
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)

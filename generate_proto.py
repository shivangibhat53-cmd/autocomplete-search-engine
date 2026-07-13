# generate_proto.py
"""
Run this script to regenerate gRPC code from the proto file.
Must be run from the project root.

Usage:
    python generate_proto.py
"""
import subprocess
import sys

result = subprocess.run([
    sys.executable, "-m", "grpc_tools.protoc",
    "-I", "proto",
    "--python_out=src/grpc_generated",
    "--grpc_python_out=src/grpc_generated",
    "proto/autocomplete.proto",
], capture_output=True, text=True)

if result.returncode != 0:
    print("  protoc failed:")
    print(result.stderr)
    sys.exit(1)

# Fix the import in the generated grpc file
grpc_file = "src/grpc_generated/autocomplete_pb2_grpc.py"
with open(grpc_file, "r") as f:
    content = f.read()

# Replace the broken relative import with the correct package import
content = content.replace(
    "import autocomplete_pb2 as autocomplete__pb2",
    "from src.grpc_generated import autocomplete_pb2 as autocomplete__pb2"
)

with open(grpc_file, "w") as f:
    f.write(content)

print("   Proto files generated successfully")
print("   src/grpc_generated/autocomplete_pb2.py")
print("   src/grpc_generated/autocomplete_pb2_grpc.py")
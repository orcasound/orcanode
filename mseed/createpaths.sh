
date=$(date '+%Y-%m-%d')

mkdir -p /tmp/$NODE_NAME
mkdir -p /tmp/$NODE_NAME/hls
mkdir -p /tmp/$NODE_NAME/hls/$date

echo "starting upload"

python3 upload_s3.py
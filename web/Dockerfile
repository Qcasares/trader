# web/Dockerfile
# --------------
# The frontend, for **local testing only**.
#
# Production deploys to Vercel — that is locked decision 6, and a Next.js
# server has no business holding a trading loop. This image exists so the whole
# stack can be brought up with one command on a laptop, which is otherwise
# impossible: the UI is the only part of the system a human actually looks at,
# and testing it by hand meant running npm separately from everything else.
#
# It runs `next dev`, not a production build. A dev server rebuilds on change,
# which is what you want while testing locally and emphatically not what you
# would ship.

FROM node:20-alpine

WORKDIR /app

# Copy the manifests first so a source change does not invalidate the
# dependency layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Bound to 0.0.0.0 so the port publishes out of the container. NEXT_PUBLIC_*
# is read at build time by Next, so it is passed as an environment variable
# here rather than baked in — the API host differs between compose and Vercel.
EXPOSE 3000
CMD ["npx", "next", "dev", "--port", "3000", "--hostname", "0.0.0.0"]

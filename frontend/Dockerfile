FROM node:20-alpine AS builder
WORKDIR /app

# Public analytics identifiers (GA4 measurement id + Clarity project id),
# inlined into the client bundle at build time. Empty by default = the page
# ships no analytics tags; CI feeds them from repo secrets as build args.
ARG NEXT_PUBLIC_GA_MEASUREMENT_ID
ARG NEXT_PUBLIC_CLARITY_ID

COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# Only copy public if it exists, or create an empty one to prevent build failure
COPY --from=builder /app/public* ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000
CMD ["npm", "start"]

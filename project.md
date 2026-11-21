# Modern Life RPG — Product Concept, MVP Specification & Technical Requirements

## 1. Product Overview

Build a mobile-first, multiplayer life gamification application designed primarily as a Telegram Mini App.

The application transforms real life into a role-playing game where two people become both players and Game Masters for each other.

Unlike traditional habit trackers and productivity applications, users do not assign themselves quests or create their own rewards. Instead, their partner or friend creates personalized quests, determines rewards, confirms completion, and helps them develop different areas of their life.

Players earn experience points (XP), Gold, character levels, and attribute progression by completing real-life activities. Gold can be exchanged for real-life rewards provided by their companion.

The product combines three complementary concepts:

- **Real-Life RPG:** character progression, levels, attributes, quests, achievements, virtual currency, and inventory.
- **Relationship Game:** meaningful interactions, personalized rewards, shared experiences, and mutual support.
- **Personal Development:** habits, discipline, accountability, productivity, and balanced growth across different areas of life.

These should not be implemented as separate game modes. They should coexist within a single cohesive experience.

The core product philosophy is:

**Help your companion become who they want to become, rather than who you want them to be.**

Potential product slogans:

- Your life. Your RPG.
- Real life. Real quests. Real rewards.
- Level up together.
- Your companion is your Game Master.
- Life is better in co-op.

## 2. Target Audience

The initial target audience includes:

- Romantic couples.
- Close friends.
- Accountability partners.
- People interested in self-improvement.
- People who enjoy RPG games and gamification.

Romantic couples are a particularly promising initial audience because they can create personalized, meaningful rewards that traditional productivity applications cannot provide.

However, the application must not be exclusively romantic. Its terminology, visual design, and core mechanics should work equally well for friends and other types of companions.

## 3. Product and Design Direction

The application should follow a Modern RPG design philosophy.

The interface should feel like a modern, premium mobile application rather than a traditional medieval fantasy game.

The underlying mechanics should be inspired by RPG games, but users should not feel overwhelmed by complex menus or fantasy terminology.

### Visual direction

- Mobile-first responsive design.
- Dark theme as the primary visual direction, with optional light theme support.
- Modern typography.
- Clean, spacious layouts.
- Rounded cards and smooth transitions.
- Purple or indigo accents for XP and character progression.
- Gold accents for currency and rewards.
- Dedicated colors for different character attributes.
- Subtle gradients and visual effects.
- Smooth progress bar animations.
- Satisfying micro-interactions when completing quests, earning Gold, purchasing rewards, and leveling up.
- Telegram-native interactions and haptic feedback where supported.
- Minimal visual clutter.
- Game-inspired icons without excessive fantasy decoration.

The application should combine the accessibility of a modern productivity application with the emotional satisfaction of an RPG.

The complexity should exist primarily in the underlying game mechanics, not in the interface.

## 4. Core Game Loop

The primary game loop consists of the following steps:

1. A companion creates a quest for the player.
2. The player reviews and accepts the quest.
3. The player completes the real-life activity.
4. The player submits the quest for confirmation.
5. The companion confirms completion.
6. The player receives Gold, general XP, and attribute-specific XP.
7. The player spends Gold on real-life rewards created by the companion.
8. The player uses purchased rewards.
9. Both players continue creating quests and progressing together.

Every user has two simultaneous roles.

### Player

- Receives quests.
- Accepts or declines quests.
- Completes real-life activities.
- Earns XP and Gold.
- Develops character attributes.
- Purchases and uses rewards.

### Game Master

- Creates quests for their companion.
- Determines Gold rewards.
- Selects quest difficulty and attributes.
- Reviews quest submissions.
- Creates real-life rewards.
- Manages reward availability.
- Supports their companion's personal development.

Both users have equal permissions.

There is no primary administrator or superior player within a partnership.

## 5. MVP Scope

The initial MVP should include:

1. Character creation and companion invitations.
2. Quest creation and acceptance.
3. Quest completion and confirmation.
4. XP, Gold, levels, and basic character attributes.
5. Real-life reward shop.
6. Reward inventory and redemption.
7. Progress history.
8. Life balance visualization.
9. Telegram bot notifications.
10. Personal development goals and reward wishlist.

The core functionality should initially support exactly two connected players.

Support for multiple companions, groups, guilds, and larger multiplayer communities should be considered future functionality.

## 6. Character Creation and Onboarding

Authentication should be handled through Telegram.

Users should not need to create a separate account, remember a password, or manually enter their email address.

The application should retrieve available Telegram profile information after securely validating Telegram Mini App initialization data.

### Onboarding flow

**Step 1: Create your character**

- Display name, initially populated from Telegram.
- Avatar, initially populated from the Telegram profile when available.
- Optional character nickname.
- Optional short personal description.

**Step 2: Choose your goals**

Allow users to select the areas of life they want to develop.

Examples:

- Exercise more frequently.
- Improve discipline.
- Read more books.
- Improve relationships.
- Learn new skills.
- Spend more time on creative activities.
- Improve sleep and recovery.

These goals are informational and help the companion create relevant quests.

**Step 3: Invite your companion**

Generate a unique invitation link or invitation code.

The invitation should open the Telegram Mini App and allow another Telegram user to accept the invitation.

The partnership becomes active only after the invited user accepts.

**Step 4: Start your adventure**

Once both players are connected, the complete application functionality becomes available.

### Initial character state

Every new character starts with:

- Level 1.
- 0 XP.
- 0 Gold.
- All character attributes at Level 1.
- No completed quests.
- Empty reward inventory.
- No achievements.

Character classes should not be included in the MVP.

In future versions, character specialization could emerge naturally based on the types of quests the player completes.

### Character profile

The character profile should display:

- Avatar.
- Character name.
- Current level.
- Current XP.
- XP required for the next level.
- Progress bar.
- Gold balance.
- Total completed quests.
- Activity statistics.
- Character attributes.
- Connected companion.
- Personal development goals.
- Wishlist.

## 7. Quest System

The quest system is the central feature of the application.

Creating a quest should be fast and intuitive, ideally taking no more than 15–30 seconds.

Users can only assign quests to their connected companion, not to themselves.

### Quest creation fields

- Quest title.
- Optional description.
- Character attribute.
- Difficulty.
- Gold reward.
- Automatically calculated XP reward.
- Recurrence type.
- Optional deadline.
- Completion confirmation method.
- Optional photo proof requirement.

### Example quest

Title: Go to the gym

Description: Complete a full workout.

Attribute: Physical

Difficulty: Normal

Gold reward: 50

XP reward: 50

Frequency: Daily

Confirmation: Manual confirmation by companion.

### Quest types

**One-time quest**

A quest that can be completed once.

Example: Organize a surprise date.

**Daily quest**

A recurring quest that generates one quest occurrence per day.

Example: Read 20 pages.

**Weekly quest**

A quest that repeats every week.

Example: Complete three workouts during the week.

For the MVP, weekly quests can use a simple completion checkbox. More advanced progress counters can be introduced later.

**Open quest**

A quest without a specific deadline that remains available until completed or cancelled.

Example: Learn a new song on the guitar.

### Recurring quest behavior

Recurring quest templates should generate individual quest occurrences.

Each occurrence must have its own completion status, deadline, submission, and reward transaction.

When a recurring quest is accepted, future occurrences should not require repeated acceptance unless the quest terms change.

Users should be able to pause or discontinue recurring quests.

Changes to recurring quest conditions should apply to future occurrences only and require renewed acceptance.

Previously completed occurrences must retain their original reward values and conditions.

### Quest lifecycle

The main quest statuses are:

- Offered.
- Active.
- In Review.
- Completed.
- Declined.
- Expired.
- Cancelled.

The normal lifecycle is:

Offered → Active → In Review → Completed.

Additional transitions include:

- Offered → Declined.
- Active → Expired.
- Active → Cancelled.
- In Review → Active, when the companion requests corrections.

### Quest acceptance rules

Receiving a quest should not automatically create an obligation.

The player must explicitly accept or decline the quest.

Declining a quest must not result in penalties, Gold deductions, or XP loss.

After a quest is accepted, the creator cannot unilaterally reduce the reward, increase the difficulty, or change its completion conditions.

Changes to accepted quest conditions require renewed agreement.

### Quest deadlines

Quests can optionally have deadlines.

When a quest deadline passes without a valid completion submission, the quest becomes expired.

An expired quest does not award XP or Gold.

If a player submitted a quest before its deadline, the companion should still be able to review it after the deadline passes.

The MVP should not include financial penalties, negative Gold balances, or XP reductions for expired quests.

## 8. Quest Completion and Confirmation

When a player completes a quest, they can submit it for confirmation.

The submission may contain:

- Completion confirmation.
- Optional comment.
- Optional photograph.
- Submission timestamp.

The companion receives a notification and can review the submission.

### Manual confirmation

The companion can:

- Confirm completion.
- Request corrections.
- Provide optional positive feedback.

If corrections are requested, a reason must be provided.

The quest returns to Active status.

Once confirmed, the system automatically awards:

- Gold.
- General XP.
- Attribute-specific XP.

Rewards must be distributed exactly once per completed quest occurrence.

### Automatic confirmation

Some quests can use automatic confirmation based on mutual trust.

For example, a daily reading quest can be marked as completed without requiring the companion to approve it manually every day.

The quest creator chooses the confirmation method when creating the quest.

This is particularly important for recurring quests because excessive manual confirmations could create unnecessary friction.

### Notifications

The application should notify users when:

- A new quest is offered.
- A submitted quest requires confirmation.
- A quest is confirmed.
- Corrections are requested.
- An accepted quest is approaching its deadline.

Notification delivery should be configurable to avoid overwhelming users.

## 9. Character Progression System

Character progression consists of three separate systems:

- General XP and character levels.
- Attribute-specific XP and attribute levels.
- Gold currency.

These systems serve different purposes and must remain logically separate.

### General XP

XP represents permanent character progression.

XP cannot be spent, exchanged, or transferred.

XP is earned by successfully completing quests.

The amount of XP earned depends on quest difficulty rather than the amount of Gold assigned by the companion.

### Quest difficulty

Use the following initial balancing values:

| Difficulty | XP Reward | Recommended Gold |
|---|---:|---:|
| Easy | 20 XP | 10–20 Gold |
| Normal | 50 XP | 30–50 Gold |
| Hard | 100 XP | 60–100 Gold |
| Epic | 250 XP | 150–250 Gold |

The system automatically determines XP based on difficulty.

The Game Master manually determines Gold.

Recommended Gold values should be presented as guidance rather than mandatory prices.

All balancing values should be configurable for future adjustments.

### Character levels

Characters should use an unlimited progression system with gradually increasing XP requirements.

Initial formula:

XP required for the next level = 100 + (current level − 1) × 50.

Examples:

| Current Level | XP Required for Next Level |
|---|---:|
| 1 | 100 |
| 2 | 150 |
| 3 | 200 |
| 5 | 300 |
| 10 | 550 |
| 20 | 1,050 |
| 50 | 2,550 |

The total accumulated XP required to reach level L is:

Total XP = 100 × (L − 1) + 25 × (L − 1) × (L − 2).

XP earned beyond the current level threshold should carry over to the next level.

A sufficiently large XP reward may trigger multiple level increases.

Character levels must never decrease because of inactivity or incomplete quests.

Level-up events should trigger satisfying visual feedback and optionally Telegram notifications.

## 10. Character Attributes

The MVP should include six universal character attributes.

### Physical

Represents activity related to physical development.

Example quests:

- Complete a workout.
- Go for a run.
- Play a sport.
- Walk 10,000 steps.

### Intellectual

Represents learning and intellectual development.

Example quests:

- Read 20 pages.
- Complete a course lesson.
- Practice a foreign language.
- Study a new topic.

### Discipline

Represents consistency, organization, and productivity.

Example quests:

- Complete a planned work session.
- Finish an important personal task.
- Organize your workspace.
- Follow a morning routine.

### Social

Represents communication, relationships, and meaningful interactions.

Example quests:

- Organize a date.
- Call a friend.
- Plan a shared activity.
- Spend quality time together.

### Creativity

Represents creative activities and hobbies.

Example quests:

- Draw something.
- Practice a musical instrument.
- Write a short story.
- Work on a creative project.

### Wellbeing

Represents rest, recovery, and self-care.

Example quests:

- Get sufficient sleep.
- Meditate for 15 minutes.
- Spend time outdoors.
- Take a relaxing evening away from work.

### Attribute progression

Every quest is associated with one primary attribute.

Completing a quest awards both general XP and attribute-specific XP.

Example:

Completing a Normal Physical quest awards:

- 50 general XP.
- 50 Physical XP.
- The Gold reward specified by the companion.

Attribute-specific XP contributes to the level of the corresponding attribute.

Individual attribute levels should be permanent and should not decrease due to inactivity.

For the MVP, the same progression formula can be used for general character levels and individual attribute levels.

Attributes represent completed activities and game progression, not objective measurements of intelligence, health, personality, or human value.

## 11. Life Balance System

The application should include a Life Balance Wheel visualized as an interactive radar chart.

It should use the same six character attributes:

- Physical.
- Intellectual.
- Discipline.
- Social.
- Creativity.
- Wellbeing.

The Life Balance Wheel must be separate from permanent character attribute levels.

### Permanent attributes vs. current activity

Permanent attributes represent long-term accumulated experience.

The Life Balance Wheel represents recent activity.

For example, a player may have Physical Level 25 but may not have completed any Physical quests during the past two weeks.

Their permanent Physical level remains unchanged, while their recent Physical activity score decreases.

### Time ranges

Allow users to switch between:

- Last 7 days.
- Last 30 days.

Additional time ranges can be introduced later.

### Calculation

Each attribute should have a configurable activity target for the selected period.

Example formula:

Activity score = min(100, earned attribute XP / target attribute XP × 100).

An activity score represents progress toward an agreed activity target, not an assessment of the person's actual quality of life.

### Companion interaction

The companion should be able to view the player's recent activity distribution.

The application can suggest quest categories based on areas with lower recent activity.

Example:

"Your companion has completed fewer creative activities this week. Consider offering a creative quest."

These suggestions should remain optional and encouraging rather than judgmental.

AI is not required for the initial implementation. Suggestions can be generated using simple predefined rules.

## 12. Gold Economy

Gold is the spendable virtual currency of the application.

Players earn Gold by completing quests and spend it exclusively on rewards created by their companion.

Gold has no real-world monetary value.

It cannot be purchased with real money, withdrawn, traded, or transferred between unrelated users in the MVP.

### Currency generation

Gold is generated by the system when a quest is successfully completed.

Gold is not deducted from the Game Master's personal balance.

Example:

Player A creates a quest for Player B with a reward of 50 Gold.

When Player B completes the quest, the system generates 50 Gold and credits Player B's account.

Player A's personal balance remains unchanged.

### Currency consumption

Gold is removed from the available balance when a reward is purchased.

The purchase should create a corresponding reward inventory item.

Purchased Gold should not be credited to the reward creator's balance.

If a purchased reward is cancelled and refunded, the original purchase amount is returned through a separate transaction.

Gold must never be deducted twice for the same reward.

### Economy balancing

Suggested reward pacing:

- Small rewards: achievable after 1–3 days.
- Medium rewards: achievable after approximately one week.
- Large rewards: achievable after one month or longer.

Players should ultimately control the economy of their partnership.

The application should provide guidance about potential currency inflation.

For example, when creating a recurring quest, the Game Master should see its estimated weekly and monthly Gold generation.

Example:

Daily quest reward: 50 Gold.

Potential weekly earnings: 350 Gold.

Potential monthly earnings: approximately 1,500 Gold.

This helps players establish reasonable reward prices.

### Transaction history

Every Gold balance change must be recorded.

Transaction categories include:

- Quest completion.
- Reward purchase.
- Reward refund.
- Future system adjustments, if introduced.

The Gold balance must never become negative.

Gold transactions should be atomic and idempotent.

## 13. Real-Life Reward Shop

The Reward Shop is one of the primary differentiating features of the application.

Each player maintains a personal shop containing rewards they are willing to provide to their companion.

Players cannot create rewards for themselves and immediately purchase them.

### Shop structure

The Shop section should contain:

- Rewards available for purchase.
- My Inventory.
- Manage My Shop.
- Reward requests awaiting fulfillment.

### Example rewards

| Reward | Example Price |
|---|---:|
| Choose tonight's movie | 80 Gold |
| Breakfast in bed | 100 Gold |
| Gaming evening | 100 Gold |
| 30-minute massage | 150 Gold |
| Favorite homemade dinner | 200 Gold |
| Surprise gift | 350 Gold |
| Surprise date | 500 Gold |
| Full day of planned activities | 800 Gold |
| Weekend getaway | 1,500 Gold |

These prices are examples only.

### Reward creation fields

- Reward name.
- Optional description.
- Gold price.
- Optional image.
- Optional purchase quantity limit.
- Optional cooldown.
- Availability status.
- Optional fulfillment conditions.

### Availability

Rewards can be:

- Active.
- Hidden.
- Sold out.

Reward creators can change prices or availability for future purchases.

Previously purchased rewards must retain their original conditions and purchase price.

### Quantity limits

A reward can have either unlimited availability or a fixed number of available purchases.

For example, a player may offer only three massage rewards.

Each purchase decreases the available quantity.

Quantity validation must happen on the backend.

### Cooldown

A reward can optionally have a purchase cooldown.

For example, a particular reward may only be purchased once every seven days.

Cooldown logic should be enforced by the backend.

## 14. Reward Inventory

The inventory represents purchased real-life reward vouchers.

Unlike a traditional RPG inventory containing weapons, armor, and potions, this inventory contains experiences and benefits provided by the player's companion.

Purchasing a reward does not necessarily mean using it immediately.

Example:

A player purchases a massage reward today but chooses to request its fulfillment three days later.

The reward remains in their inventory.

### Reward lifecycle

Purchased → Requested → Scheduled → Fulfilled.

Additional statuses:

- Cancelled.
- Refunded.

### Purchasing a reward

1. The player selects a reward.
2. The system checks the available Gold balance.
3. The system validates availability, quantity, and cooldown restrictions.
4. Gold is deducted from the player's available balance.
5. A reward voucher is added to the player's inventory.
6. The transaction is recorded.

### Using a reward

1. The player opens their inventory.
2. The player selects an available reward voucher.
3. The player requests fulfillment.
4. The companion receives a notification.
5. Both players coordinate the time and conditions.
6. The reward is fulfilled.
7. The inventory item is marked as used.

Rewards should not expire automatically in the MVP unless both players have agreed to an explicit expiration condition.

### Refunds

If a reward cannot be fulfilled, it can be cancelled and refunded.

The original purchase price should be returned to the player.

Refunds must be recorded as separate Gold transactions.

The purchased reward must then become unavailable for further use.

## 15. Adventure Journal and Progress History

The application should include an Adventure Journal.

Rather than displaying only a transactional log, the journal should act as a chronological record of the player's adventure.

### Journal events

- Quest offered.
- Quest accepted.
- Quest completed.
- XP earned.
- Gold earned.
- Character level increased.
- Attribute level increased.
- Reward purchased.
- Reward requested.
- Reward fulfilled.
- Reward refunded.
- Companion connected.

### Statistics

The Stats section should display:

- Total completed quests.
- Completed quests this week.
- Completed quests this month.
- Total accumulated XP.
- XP earned during a selected period.
- Total Gold earned.
- Total Gold spent.
- Current Gold balance.
- Attribute progression.
- Activity history.
- Rewards purchased.
- Rewards fulfilled.

### Visualizations

- XP earned per day.
- Completed quests per day.
- Weekly and monthly activity charts.
- Character attribute progress bars.
- Life Balance radar chart.

Users should be able to view their own progress and relevant shared activity with their companion.

Historical events should remain understandable even if the original quest or reward is modified later.

## 16. Personal Development Goals

Users should have a dedicated section called "I Want to Improve."

This section contains personal development goals that help their companion create meaningful quests.

Example goals:

- Exercise more frequently.
- Become more disciplined.
- Improve my sleep schedule.
- Read more books.
- Learn a foreign language.
- Spend more time on creative hobbies.

Users can create, edit, and remove their own development goals.

The companion can view these goals.

Development goals do not automatically generate XP or Gold.

They are not self-assigned quests.

## 17. Reward Wishlist

Users should have a dedicated Wishlist containing rewards they would like to receive.

Example wishlist items:

- A relaxing massage.
- Breakfast in bed.
- A surprise date.
- A weekend trip.
- A gaming evening.
- A homemade dinner.

The companion can review the wishlist and optionally convert wishlist items into available shop rewards.

The companion determines whether to offer the reward and sets its price and availability.

Adding something to the Wishlist does not create an obligation or automatically make the reward purchasable.

## 18. Application Navigation

The application should use a mobile bottom navigation bar with five primary sections.

### Home

The main dashboard.

Display:

- Character level.
- Avatar.
- XP progress bar.
- Gold balance.
- Today's quests.
- Pending quest offers.
- Important notifications.
- Pending confirmations.
- Recent activity.
- Quick actions.

### Quests

Display:

- My active quests.
- Incoming quest offers.
- Recurring quests.
- Quests assigned by me.
- Quests awaiting my confirmation.
- Completed quests.
- Quest creation button.

The interface should make it immediately clear whether the user is acting as a Player or Game Master.

### Shop

Display:

- Rewards created by the companion.
- Gold balance.
- Reward categories or filters.
- My Inventory.
- Manage My Shop.
- Pending reward fulfillment requests.

### Stats

Display:

- Character attributes.
- General character progression.
- Life Balance Wheel.
- Activity statistics.
- Adventure Journal.
- Progress charts.

### Companion

Display:

- Companion avatar.
- Character name.
- Character level.
- Character attributes.
- Recent activity.
- Personal development goals.
- Wishlist.
- Quick action to create a quest.
- Quick action to create a reward.

A separate Game Master mode is not necessary.

Game Master functionality should be integrated naturally into Quests, Shop, and Companion sections.

## 19. Telegram Mini App Integration

The product must be implemented as a Telegram Mini App supported by a Telegram bot.

The Mini App provides the complete visual interface.

The Telegram bot acts as an entry point, notification channel, and companion invitation mechanism.

The primary gameplay should happen inside the Mini App rather than through traditional bot commands.

### Telegram authentication

Use Telegram Mini App initialization data for authentication.

Requirements:

- Retrieve raw Telegram initialization data on the frontend.
- Send it to the backend.
- Validate its signature using the Telegram bot token and Telegram's documented validation algorithm.
- Validate the authentication timestamp.
- Never trust unverified client-side Telegram user information.
- Create or update the corresponding user in PostgreSQL.
- Establish a secure application session.
- Do not expose the Telegram bot token to the frontend.

Traditional registration and password-based authentication are not required for the MVP.

Telegram user IDs should be stored using a database type that safely supports large integer values.

### Telegram bot functionality

The bot should support:

- /start command.
- Welcome message.
- Button to open the Mini App.
- Companion invitation links.
- Quest notifications.
- Quest confirmation notifications.
- Reward purchase and fulfillment notifications.
- Optional daily summaries.
- Optional deadline reminders.
- Notification preferences.

Example notification:

"New quest from your companion!

Go to the gym

Reward: 50 Gold + 50 XP"

The notification should include a button that opens the relevant quest inside the Mini App.

### Deep linking

Use Telegram Mini App start parameters for invitation links and navigation to relevant application screens.

Example invitation format:

https://t.me/BOT_USERNAME/APP_SHORT_NAME?startapp=invite_TOKEN

Invitation tokens must be securely generated, validated on the backend, single-use, and optionally time-limited.

Quest notifications should support deep links that open the corresponding quest details screen.

### Telegram-specific UI requirements

- Respect available viewport dimensions.
- Handle Telegram safe-area insets.
- Support mobile keyboards correctly.
- Integrate the Telegram Back Button where appropriate.
- Support Telegram theme parameters.
- Use Telegram haptic feedback where supported.
- Use Telegram closing confirmation when unsaved changes exist, if supported.
- Handle Mini App activation and reactivation gracefully.
- Avoid assuming that the application remains active in the background.
- Ensure that the interface works on Telegram for iOS, Android, and Desktop.

Use feature detection and graceful fallbacks for Telegram SDK capabilities.

### Notification scheduling

Scheduled operations must run on the backend.

Do not rely on the Telegram Mini App remaining open to:

- Generate recurring quests.
- Expire quests.
- Send reminders.
- Process scheduled notifications.
- Update activity periods.

Store each user's timezone explicitly and allow it to be changed.

Use UTC for stored timestamps and the user's configured timezone for calendar-based operations.

Bot notifications should respect Telegram's messaging permissions and the user's notification preferences.

## 20. Technology Stack

The application should use a modern, maintainable, modular architecture suitable for rapid MVP development.

Start with a modular monolith rather than microservices.

### Frontend

**React**

Use React for building the Telegram Mini App interface.

**TypeScript**

Use strict TypeScript throughout the frontend.

**Vite**

Use Vite as the development server and build system.

Next.js is not required because the application primarily operates as an authenticated single-page application inside Telegram.

**Tailwind CSS**

Use Tailwind CSS for responsive styling, design tokens, and reusable interface patterns.

**shadcn/ui**

Use shadcn/ui as the foundation for accessible and customizable UI components.

Components should be adapted for mobile usage rather than using desktop-oriented layouts without modification.

**Motion (Framer Motion)**

Use Motion for:

- Page transitions.
- Quest completion animations.
- XP progress animations.
- Gold earning animations.
- Level-up effects.
- Reward purchase feedback.
- Interactive cards and micro-interactions.

Animations should remain lightweight and respect reduced-motion preferences.

**TanStack Query**

Use TanStack Query for:

- API requests.
- Server state management.
- Caching.
- Data invalidation.
- Loading and error states.
- Background refetching.

**Zustand**

Use Zustand for lightweight global client state when necessary.

Do not duplicate server state managed by TanStack Query.

**React Router**

Use React Router for application routing and deep-link navigation.

**React Hook Form + Zod**

Use these libraries for form management, validation, and typed form schemas.

**Recharts**

Use Recharts for:

- Radar charts.
- XP charts.
- Activity charts.
- Gold transaction visualizations.
- Progress history.

**Lucide React**

Use Lucide for a consistent icon system.

**Telegram Mini Apps SDK**

Use the official Telegram Web App API or a maintained TypeScript SDK such as @tma.js/sdk-react.

Keep Telegram-specific integration behind a dedicated application abstraction where practical.

### Backend

**Python**

Use Python 3.12 or a newer compatible stable version.

**FastAPI**

Use FastAPI to implement a typed REST API and application business logic.

**Pydantic**

Use Pydantic for request validation, response serialization, and application configuration.

**SQLAlchemy 2**

Use SQLAlchemy 2 as the ORM.

Use asynchronous database operations where appropriate.

**Alembic**

Use Alembic for version-controlled database migrations.

**PostgreSQL**

Use PostgreSQL as the primary database.

All authoritative application data, balances, progression, quest states, and reward transactions must be stored in PostgreSQL.

**aiogram 3**

Use aiogram to implement the Telegram bot.

Use webhook mode in production and optionally polling mode during local development.

The Telegram bot and REST API should share the same application domain services and business logic.

**Redis**

Use Redis where necessary for:

- Rate limiting.
- Caching.
- Short-lived state.
- Background job coordination.
- Optional distributed locking.

Redis must not be the authoritative storage for Gold balances or permanent character progression.

**APScheduler**

Use APScheduler for scheduled recurring operations in the MVP.

Run the scheduler in a dedicated process to prevent duplicate execution across API workers.

Scheduled operations should be idempotent and capable of recovering after application restarts.

PostgreSQL should remain the source of truth for pending scheduled operations.

A more advanced background job system such as Dramatiq can be introduced if the workload grows.

### File storage

Use S3-compatible object storage for:

- Uploaded avatars.
- Quest completion photographs.
- Reward images.

Cloudflare R2 or another S3-compatible provider can be used.

Files should not be stored permanently on the local application server.

Validate uploaded file types and sizes.

Private quest photographs should use authorized access or short-lived signed URLs.

### Infrastructure

**Docker**

Use Docker to containerize application services.

**Docker Compose**

Use Docker Compose for local development.

Local services may include:

- Frontend.
- FastAPI application.
- Telegram bot.
- Scheduler.
- PostgreSQL.
- Redis.

**Railway**

Use Railway for initial deployment.

Suggested production services:

- Frontend hosting.
- Backend API.
- Telegram bot integration.
- Scheduler worker.
- PostgreSQL.
- Redis, if required.

All production HTTP endpoints must use HTTPS.

Use environment variables for secrets and configuration.

Do not commit secrets or Telegram bot tokens to version control.

### Testing

Frontend:

- Vitest.
- React Testing Library.
- Playwright for end-to-end tests.

Backend:

- pytest.
- pytest-asyncio.
- HTTPX for API integration tests.
- PostgreSQL-backed integration tests for transactional behavior.

Prioritize testing the core game loop, authorization, Gold transactions, recurring quest generation, and reward redemption.

## 21. Suggested Application Architecture

Use a modular monolith with clearly separated domains.

Suggested repository structure:

```text
modern-life-rpg/
  frontend/
    src/
      app/
      components/
      features/
        auth/
        character/
        companion/
        quests/
        rewards/
        inventory/
        progression/
        stats/
        notifications/
        journal/
        goals/
        wishlist/
      hooks/
      lib/
      styles/
      types/

  backend/
    app/
      api/
      core/
      db/
      modules/
        auth/
        users/
        partnerships/
        quests/
        progression/
        economy/
        rewards/
        inventory/
        journal/
        notifications/
        goals/
        wishlist/
      bot/
      jobs/
      storage/
      main.py
    migrations/
    tests/

  docker-compose.yml
  .env.example
  README.md
```

Keep business logic separated from HTTP route handlers and Telegram bot handlers.

The API and the Telegram bot should call shared domain services rather than implement duplicate game rules.

## 22. Main Database Entities

The initial database should include the following logical entities.

### User

- Internal user ID.
- Telegram user ID.
- Telegram username.
- Display name.
- Avatar URL.
- Timezone.
- Notification preferences.
- Created timestamp.
- Updated timestamp.

### Character

- Character ID.
- User ID.
- Character name.
- General accumulated XP.
- Gold balance.
- Created timestamp.

Character level can be derived from accumulated XP using the progression formula.

### Character Attribute

- Character ID.
- Attribute type.
- Accumulated attribute XP.

Attribute level can be derived from accumulated attribute XP.

### Partnership

- Partnership ID.
- First user ID.
- Second user ID.
- Status.
- Created timestamp.
- Accepted timestamp.
- Ended timestamp.

A user can have only one active partnership in the MVP.

### Partnership Invitation

- Invitation ID.
- Creator user ID.
- Secure invitation token or token hash.
- Status.
- Expiration timestamp.
- Accepted timestamp.

### Quest Template

- Quest template ID.
- Partnership ID.
- Creator user ID.
- Assigned user ID.
- Title.
- Description.
- Attribute.
- Difficulty.
- XP reward.
- Gold reward.
- Recurrence configuration.
- Confirmation method.
- Photo proof requirement.
- Template status.
- Created timestamp.

### Quest Occurrence

- Occurrence ID.
- Quest template ID.
- Assigned user ID.
- Status.
- Deadline.
- Scheduled occurrence date.
- Snapshot of accepted quest conditions.
- Accepted timestamp.
- Submitted timestamp.
- Completed timestamp.

One-time quests can also use a template with a single occurrence.

### Quest Submission

- Submission ID.
- Quest occurrence ID.
- Submitted user ID.
- Comment.
- Optional attachment reference.
- Submission timestamp.
- Review status.
- Review comment.

### Reward

- Reward ID.
- Partnership ID.
- Creator user ID.
- Title.
- Description.
- Gold price.
- Image URL.
- Quantity limit.
- Available quantity.
- Cooldown.
- Availability status.
- Created timestamp.

### Reward Purchase

- Purchase ID.
- Reward ID.
- Partnership ID.
- Purchasing user ID.
- Provider user ID.
- Original purchase price.
- Snapshot of reward conditions.
- Redemption status.
- Purchased timestamp.
- Requested timestamp.
- Scheduled timestamp.
- Fulfilled timestamp.
- Refunded timestamp.

Reward purchases act as inventory items.

### Gold Transaction

- Transaction ID.
- User ID.
- Partnership ID.
- Transaction type.
- Gold amount.
- Associated quest or reward reference.
- Idempotency key.
- Created timestamp.

### XP Transaction

- Transaction ID.
- User ID.
- Quest occurrence ID.
- General XP amount.
- Attribute type.
- Attribute XP amount.
- Created timestamp.

### Journal Event

- Event ID.
- User ID.
- Partnership ID.
- Event type.
- Related entity reference.
- Event metadata.
- Created timestamp.

### Development Goal

- Goal ID.
- User ID.
- Title.
- Optional description.
- Attribute type.
- Status.

### Wishlist Item

- Wishlist item ID.
- User ID.
- Title.
- Optional description.
- Status.
- Optional linked reward ID.

### Life Balance Target

- User ID.
- Attribute type.
- Weekly XP target.

### Notification

- Notification ID.
- Recipient user ID.
- Notification type.
- Related entity reference.
- Delivery status.
- Delivery attempts.
- Created timestamp.
- Delivered timestamp.

## 23. Backend API Structure

Use REST endpoints organized by application domain.

Suggested endpoints:

```text
POST   /api/auth/telegram
GET    /api/auth/me

GET    /api/character
GET    /api/character/attributes
PATCH  /api/character

POST   /api/partnership/invitations
POST   /api/partnership/invitations/accept
GET    /api/partnership
POST   /api/partnership/leave

GET    /api/quests
POST   /api/quests
GET    /api/quests/{id}
PATCH  /api/quests/{id}
POST   /api/quests/{id}/accept
POST   /api/quests/{id}/decline
POST   /api/quests/{id}/submit
POST   /api/quests/{id}/confirm
POST   /api/quests/{id}/request-redo
POST   /api/quests/{id}/cancel

POST   /api/quest-templates/{id}/pause
POST   /api/quest-templates/{id}/resume

GET    /api/rewards
POST   /api/rewards
PATCH  /api/rewards/{id}
POST   /api/rewards/{id}/purchase

GET    /api/inventory
POST   /api/inventory/{id}/request
POST   /api/inventory/{id}/schedule
POST   /api/inventory/{id}/fulfill
POST   /api/inventory/{id}/refund

GET    /api/economy/balance
GET    /api/economy/transactions

GET    /api/stats
GET    /api/stats/life-balance
PUT    /api/stats/life-balance/targets

GET    /api/journal

GET    /api/goals
POST   /api/goals
PATCH  /api/goals/{id}
DELETE /api/goals/{id}

GET    /api/wishlist
POST   /api/wishlist
PATCH  /api/wishlist/{id}
DELETE /api/wishlist/{id}

GET    /api/notifications
PATCH  /api/notifications/preferences
POST   /api/notifications/{id}/read
```

These endpoints are an initial proposal and can be refined during architectural planning.

## 24. Security and Business Rules

The backend must be the authoritative source of all game state.

Never trust Gold, XP, user identity, reward prices, or quest completion values submitted directly by the frontend.

### Authorization rules

- Users can only access their own data and explicitly shared companion data.
- Users cannot assign quests to themselves.
- Users cannot confirm their own manually reviewed quests.
- Users cannot purchase rewards from their own shop.
- Users cannot manipulate another player's balance.
- Users cannot access unrelated partnerships.
- Partnership invitations require explicit acceptance.
- Users can leave a partnership without requiring permission from the other participant.

### Transaction integrity

Quest confirmation must execute as a single database transaction.

The transaction should:

1. Validate the quest status.
2. Validate the reviewing user's permissions.
3. Mark the quest as completed.
4. Credit Gold.
5. Credit general XP.
6. Credit attribute XP.
7. Create transaction records.
8. Create journal events.

Reward purchasing must also execute as a single database transaction.

Use appropriate database constraints, row locking, and idempotency mechanisms to prevent:

- Duplicate Gold rewards.
- Duplicate XP rewards.
- Duplicate reward purchases caused by repeated requests.
- Negative balances.
- Overselling limited rewards.
- Duplicate recurring quest occurrences.
- Invalid state transitions.

External notifications should be delivered after successful transaction commits.

### Partnership termination

Define explicit partnership termination behavior.

Recommended initial rules:

- Either participant can end the partnership.
- Active quest creation and new reward purchases are disabled.
- Historical quest completion and permanent XP remain available to their respective owners.
- Unfulfilled reward purchases can be cancelled and refunded.
- Unspent Gold remains associated with the original partnership and cannot automatically be spent on a new companion's rewards.
- Access to the former companion's private profile information and uploaded files is revoked.

### Privacy

Quest photographs, private comments, personal goals, and reward requests may contain sensitive information.

Access must be restricted to authorized participants.

Provide a mechanism for users to delete their account and personal data.

Avoid collecting unnecessary Telegram profile information.

## 25. Product Philosophy and Relationship Safety

The application should support healthy cooperation rather than control.

Quests are voluntary proposals, not obligations.

The ability to decline quests must always remain available.

The MVP should not include punishments for missed quests.

Reward creation must be voluntary.

Real-life rewards must respect both participants' consent at the time of fulfillment.

Basic personal freedoms, privacy, ordinary care, affection, and fundamental relationship responsibilities should never require payment with Gold.

The application should encourage meaningful cooperation without turning the relationship into a transactional obligation.

The intended experience is mutual motivation through playful interaction.

## 26. Future Game Mechanics — Post-MVP

The application architecture should allow future expansion without implementing these systems prematurely.

### Character classes

Character classes could emerge based on completed quests.

Examples:

- Warrior — Physical development.
- Scholar — Intellectual development.
- Strategist — Discipline.
- Bard — Social development.
- Creator — Creativity.
- Guardian — Wellbeing.

### Skill trees

Individual attributes could unlock special abilities.

Examples:

- Streak Shield.
- Bonus XP.
- Quest reroll.
- Additional customization.
- Progression milestones.

### Shared quests

Both companions contribute to a common objective.

Examples:

- Walk a combined distance of 50 kilometers.
- Complete a shared fitness challenge.
- Organize a trip together.
- Learn a new skill together.

### Boss battles

Large shared objectives represented as bosses with health bars.

Completing individual or shared quests contributes damage toward defeating the boss.

### Questlines

Multi-stage adventures consisting of connected quests.

Example:

"The Path of Strength"

- Complete three workouts.
- Walk 10,000 steps.
- Prepare a healthy dinner.
- Achieve a personal fitness milestone.
- Complete a cooperative fitness challenge.

### Mystery quests

A companion creates a surprise quest with hidden details.

The player may initially see the category, difficulty, and potential reward.

The full quest conditions must be revealed before the player makes a binding acceptance decision.

### Random events

Optional temporary gameplay modifiers.

Examples:

- Bonus XP for creative quests.
- Double XP weekends.
- Special achievements.
- Cooperative challenges.

### Quest negotiation

Players can propose alternative:

- Gold rewards.
- Deadlines.
- Difficulty levels.
- Completion conditions.

### Achievements

Permanent milestones, badges, and titles.

### Game Master progression

A separate progression system rewarding players for creating meaningful quests and supporting their companions.

Game Master progression could unlock cosmetic features and additional quest templates.

It must not grant greater authority over the other player.

### Shared currency

A future shared currency earned through cooperative activities.

This currency could unlock special adventures or jointly agreed experiences.

### Additional companions

Support for multiple friends, companions, groups, and cooperative communities.

### AI-powered assistance

Optional AI assistance could suggest:

- Personalized quests.
- Balanced Gold rewards.
- Reward ideas.
- Questlines.
- Development activities based on stated goals.
- Weekly progress summaries.

AI should assist Game Masters rather than replace their role.

## 27. Implementation Priorities

### P0 — Core functional MVP

- Telegram authentication.
- Character profile creation.
- Companion invitation and pairing.
- Quest creation.
- Quest acceptance and rejection.
- Quest completion.
- Manual confirmation.
- Automatic confirmation.
- Recurring quest generation.
- Gold transactions.
- General XP and character levels.
- Reward creation.
- Reward purchasing.
- Reward inventory.
- Reward fulfillment and refunds.

### P1 — Complete initial public release

- Six character attributes.
- Attribute progression.
- Life Balance Wheel.
- Progress history.
- Adventure Journal.
- Telegram notifications.
- Photo proof.
- Personal development goals.
- Reward Wishlist.
- Quest templates.
- UI animations and haptic feedback.
- Notification preferences.

### Post-MVP

- Character classes.
- Achievements and titles.
- Skill trees.
- Shared quests.
- Boss battles.
- Questlines.
- Mystery quests.
- Random events.
- Shared currencies.
- Multiple companions.
- AI assistance.

## 28. Development Instructions

Before implementing the application:

1. Review the complete product specification.
2. Identify unclear or conflicting requirements.
3. Propose the overall technical architecture.
4. Define the database schema and entity relationships.
5. Define valid quest and reward state transitions.
6. Define the Gold and XP transaction logic.
7. Plan the Telegram authentication and invitation flows.
8. Define frontend screens and reusable components.
9. Break implementation into small, independently testable milestones.
10. Prioritize the complete end-to-end core game loop before secondary functionality.

Do not attempt to implement all future RPG mechanics in the MVP.

Avoid unnecessary complexity, premature microservices, excessive dependencies, and overengineering.

Use modern coding practices, strong typing, clear naming conventions, reusable components, and comprehensive validation.

The first functional milestone should allow two Telegram users to:

- Open the Mini App.
- Authenticate automatically.
- Create their characters.
- Connect with each other.
- Assign and accept a quest.
- Complete and confirm the quest.
- Receive Gold and XP.
- Create a real-life reward.
- Purchase it using earned Gold.
- Request and confirm reward fulfillment.

Once this complete loop works reliably, expand the character progression, statistics, design, and secondary features.

The final product should feel like a real cooperative game built around everyday life, not simply a task manager with points.

**Real life is the game world. Your companion is your Game Master. Every meaningful action is an opportunity to level up.**
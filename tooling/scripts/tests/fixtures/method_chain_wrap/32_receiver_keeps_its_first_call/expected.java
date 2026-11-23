public class Demo
{
    void schedule()
    {
        followUpScheduler.createTaskBuilder(REFRESH_ENTITY.toString())
            .resource(ENTITY_RESOURCE_KEY, followUpId)
            .parameter(RefreshEntityHandler.ENTITY_ID_KEY, followUpId)
            .schedule(true);
    }

    void nested()
    {
        JsonObject coreSettings = Json.createObjectBuilder()
            .add(
                "SQL",
                Json.createObjectBuilder()
                    .add("CONNECTION",
                         "postgresql://user:pass@localhost:5432/dbname"))
            .build();
    }

    void tooWideToShare()
    {
        long followUpDelay = scheduling
            .getJsonNumber(AbstractSchedulingService.FOLLOW_UP_DELAY_KEY)
            .longValue();
    }
}

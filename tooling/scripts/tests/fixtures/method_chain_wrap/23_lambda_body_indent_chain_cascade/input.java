public class Demo
{
    public void run(Some entity)
    {
        entity.getRelatedEntities().values().forEach(related -> {
            SzMatchType matchType = related.getMatchType();
            String matchKey = related.getMatchKey();
        });
    }
}

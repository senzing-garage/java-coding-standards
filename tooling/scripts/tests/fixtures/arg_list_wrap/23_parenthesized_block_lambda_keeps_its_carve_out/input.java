public class Demo
{
    public void run(Map<String, Set<String>> relatedSources)
    {
        relatedSources.forEach(((relationKey, relatedSourceSet) -> {
            relatedSourceSet.forEach(relatedSource -> {
                result.put(relationKey, relatedSource);
            });
        }));
    }
}

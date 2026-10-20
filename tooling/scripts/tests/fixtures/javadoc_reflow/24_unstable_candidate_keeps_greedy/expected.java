public class Demo
{
    /**
     * Checks whether this element can be merged with other mergeable elements
     * that are identical to it for a single call to {@link
     * SampleHandler#handleElement(String, Map, int, Registry)} with an
     * incrementally increased multiplicity.
     */
    public boolean isMergeable()
    {
        return false;
    }
}

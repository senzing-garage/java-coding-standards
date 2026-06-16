public class Demo
{
    public void run()
        throws Exception
    {
        try {
            try (InputStream is
                     = cls.getResourceAsStream(POM_PROPERTIES_PATH)) {
                props.load(is);
            }
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }
}

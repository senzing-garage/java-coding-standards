public class Demo
{
    public void run(java.io.Reader reader, String csvFormat)
    {
        try {
            this.parser = Builder.builder()
                                 .setReader(reader)
                                 .setFormat(csvFormat)
                                 .get();
        } catch (RuntimeException e) {
            throw e;
        }
    }
}
